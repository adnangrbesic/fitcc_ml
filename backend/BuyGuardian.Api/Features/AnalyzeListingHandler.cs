using MediatR;
using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Models;
using BuyGuardian.Api.Interfaces;
using System.Text.Json;

namespace BuyGuardian.Api.Features;

public class AnalyzeListingHandler : IRequestHandler<AnalyzeListingQuery, ListingAnalysisResult>
{
    private readonly BuyGuardianContext _context;
    private readonly ICacheService _cache;
    private readonly IMlService _mlService;
    private readonly IHttpClientFactory _httpClientFactory;

    public AnalyzeListingHandler(BuyGuardianContext context, ICacheService cache, IMlService mlService, IHttpClientFactory httpClientFactory)
    {
        _context = context;
        _cache = cache;
        _mlService = mlService;
        _httpClientFactory = httpClientFactory;
    }

    public async Task<ListingAnalysisResult> Handle(AnalyzeListingQuery request, CancellationToken cancellationToken)
    {
        var cacheKey = $"analysis:{request.ItemId}";
        var cached = await _cache.GetAsync<ListingAnalysisResult>(cacheKey);
        if (cached != null) return cached;

        var listing = await _context.Listings
            .Include(l => l.Seller)
            .Include(l => l.Product)
            .Include(l => l.PriceHistories)
            .FirstOrDefaultAsync(l => l.ItemId == request.ItemId, cancellationToken);

        if (listing == null)
            throw new KeyNotFoundException($"Listing {request.ItemId} not found");

        // ── Dynamic Seller Trust Score ────────────────────────────────────
        double sellerTrust = 0.5;
        if (listing.Seller != null)
        {
            sellerTrust = CalculateSellerTrust(listing.Seller);
            listing.Seller.TrustScore = sellerTrust;
        }

        var trustScoreResult = await _mlService.GetTrustScoreAsync(listing, retrain: false);
        if (trustScoreResult == null)
        {
            throw new TrustScoreUnavailableException(
                $"Trust score service unavailable for listing {request.ItemId}.");
        }

        var normalizedTrust = Math.Clamp(trustScoreResult.TrustScore / 10.0, 0.0, 1.0);
        listing.TrustScore = normalizedTrust;

        // ── Isolation Forest Anomaly Detection ───────────────────────────
        var anomalyResult = await _mlService.GetAnomalyScoreAsync(request.ItemId);
        if (anomalyResult != null)
        {
            listing.AnomalyScore = anomalyResult.AnomalyScore;
            listing.IsAnomaly = anomalyResult.IsAnomaly;
            listing.AnomalyType = anomalyResult.AnomalyType;
        }

        await _context.SaveChangesAsync(cancellationToken);

        var isSuspicious = listing.TrustScore < 0.4 || (listing.IsAnomaly == true);
        var isNewSeller = listing.Seller != null && listing.Seller.AccountAgeMonths < 3;
        var overallScore = CalculateOverallTrustScore(
            listing.TrustScore.Value * 10.0,
            sellerTrust * 10.0,
            listing.Seller,
            listing.IsAnomaly,
            listing.AnomalyType
        );
        
        // Extract richer data
        var risks = new List<string>();
        if (listing.TrustScore < 0.4) risks.Add("low_trust");
        if (listing.PriceHistories.Count < 2) risks.Add("new_listing");
        if (listing.Seller?.AccountAgeMonths < 3) risks.Add("new_account");
        if (string.IsNullOrWhiteSpace(listing.Description) || listing.Description.Trim().Length < 5)
        {
            risks.Add("empty_description");
        }
        if (listing.IsAnomaly == true && !string.IsNullOrEmpty(listing.AnomalyType))
        {
            string type = listing.AnomalyType.Replace("anomaly_", "").Trim();
            risks.Add($"anomaly_{type}");
        }

        // Resolve contradictions: Can't be "New" and "Stale" simultaneously. 
        // If stale is explicit from ML/Scrape, hide the base "new_listing" database tag.
        if (risks.Contains("anomaly_listing_staleness") && risks.Contains("new_listing"))
        {
            risks.Remove("new_listing");
        }

        int? warranty = null;
        if (listing.RawMetadata.TryGetValue("context", out var ctx) && ctx is JsonElement ctxElem)
        {
            if (ctxElem.TryGetProperty("warranty_months", out var wElem) && wElem.TryGetInt32(out var w))
                warranty = w;
        }

        // --- EXTRACT UI ALERTS ---
        var uiAlerts = new List<string>();
        if (listing.RawMetadata.TryGetValue("ui_alerts", out var alertsObj) && alertsObj is JsonElement alertsElem && alertsElem.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in alertsElem.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String)
                {
                    uiAlerts.Add(item.GetString()!);
                }
            }
        }
        // -------------------------
        // Locate exact same product group price minimum for end user reality check
        // Fetch top 5 logical candidates to run a live verification check on
        var candidates = new List<dynamic>();
        if (listing.ProductId.HasValue)
        {
            var rawList = await _context.Listings
                .Where(l => l.ProductId == listing.ProductId && l.IsActive && l.ItemId != listing.ItemId && l.Price > 0)
                .Where(l => l.TrustScore > 0.65)
                .OrderBy(l => l.Price)
                .Take(5) 
                .Select(l => new { 
                    ItemId = l.ItemId, 
                    Price = l.Price, 
                    Title = l.Title, 
                    SellerName = l.Seller != null ? l.Seller.Username : "Nepoznat" 
                })
                .ToListAsync(cancellationToken);
            
            foreach(var item in rawList) candidates.Add(item);
        }

        // Dynamic real-time survival check engine
        dynamic? verifiedCheapest = null;
        var client = _httpClientFactory.CreateClient();
        client.Timeout = TimeSpan.FromSeconds(1.5); // Ultra tight timeout for fast responses

        foreach (var c in candidates)
        {
            try 
            {
                string cleanId = c.ItemId.ToString().TrimStart('/');
                // Send light HEAD or GET request to olx verification endpoint
                var response = await client.GetAsync($"https://www.olx.ba/artikal/{cleanId}", HttpCompletionOption.ResponseHeadersRead, cancellationToken);
                
                if (response.IsSuccessStatusCode)
                {
                    verifiedCheapest = c; // Found first live one!
                    break;
                }
            }
            catch
            {
                // Silently continue to next candidate if current one times out or errors
                continue;
            }
        }

        var result = new ListingAnalysisResult(
            listing.ItemId,
            listing.Title,
            listing.TrustScore.Value * 10, // UI expects 0-10
            overallScore,
            $"Analiza za {listing.Title}. Trust: {listing.TrustScore:P0}.",
            isSuspicious,
            listing.Product?.AvgPrice ?? listing.Price,
            listing.Price,
            risks.ToArray(),
            sellerTrust, // Use the freshly calculated seller trust (0.0-1.0)
            isNewSeller,
            listing.Product?.CategoryName,
            listing.Product?.CanonicalName,
            warranty,
            // Isolation Forest anomaly detection
            listing.AnomalyScore,
            listing.IsAnomaly,
            listing.AnomalyType,
            listing.Seller?.PositiveFeedback,
            listing.Seller?.NegativeFeedback,
            listing.Seller?.SuccessfulDeliveries,
            listing.Seller?.AccountAgeMonths,
            verifiedCheapest?.ItemId,
            verifiedCheapest?.Price,
            verifiedCheapest?.Title,
            verifiedCheapest?.SellerName,
            uiAlerts.ToArray()
        );

        await _cache.SetAsync(cacheKey, result, TimeSpan.FromHours(1));

        return result;
    }

    private double CalculateStandardDeviation(IEnumerable<double> values)
    {
        double avg = values.Average();
        return Math.Sqrt(values.Average(v => Math.Pow(v - avg, 2)));
    }

    private static double CalculateOverallTrustScore(
        double listingScore,
        double sellerScore,
        Seller? seller,
        bool? isAnomaly,
        string? anomalyType)
    {
        const double sellerPrior = 7.0;
        const double sellerPriorStrength = 15.0; // Slightly more responsive to new feedback
        double evidence = seller is null ? 0.0 : CalculateSellerEvidenceCount(seller);
        double weight = evidence / (evidence + sellerPriorStrength);
        double sellerAdjusted = (weight * sellerScore) + ((1.0 - weight) * sellerPrior);
        
        // 60% Listing, 40% Seller for better balance
        double baseScore = (0.6 * listingScore) + (0.4 * sellerAdjusted);
        
        double penalty = CalculateAnomalyPenalty(isAnomaly, anomalyType);
        return Math.Clamp(baseScore - penalty, 1.0, 10.0);
    }

    private static double CalculateSellerEvidenceCount(Seller seller)
    {
        int positive = Math.Max(0, seller.PositiveFeedback);
        int neutral = Math.Max(0, seller.NeutralFeedback);
        int negative = Math.Max(0, seller.NegativeFeedback);
        int deliveries = Math.Max(0, seller.SuccessfulDeliveries);

        int feedbackCount = Math.Min(positive + neutral + negative, 100);
        int deliveryCount = Math.Min(deliveries, 50);
        return feedbackCount + deliveryCount;
    }

    private static double CalculateAnomalyPenalty(bool? isAnomaly, string? anomalyType)
    {
        if (isAnomaly != true)
        {
            return 0.0;
        }

        string normalized = (anomalyType ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized.Contains("suspicious")
            || normalized.Contains("too_good")
            || normalized.Contains("condition_price_mismatch"))
        {
            return 2.0;
        }

        if (normalized.Contains("underpriced")
            || normalized.Contains("overpriced")
            || normalized.Contains("price_anomaly")
            || normalized.Contains("price_deviation"))
        {
            return 1.3;
        }

        return 0.7;
    }

    /// <summary>
    /// Dynamic multi-factor seller trust score (0.0–1.0) from Seller entity.
    /// Mirrors the ListingConsumer formula but reads from the DB entity directly.
    /// </summary>
    private static double CalculateSellerTrust(Seller seller)
    {
        double ageScore = Math.Min(seller.AccountAgeMonths / 36.0, 1.0);

        int totalFeedback = seller.PositiveFeedback + seller.NeutralFeedback + seller.NegativeFeedback;
        double feedbackScore = totalFeedback == 0
            ? 0.5
            : (double)seller.PositiveFeedback / (seller.PositiveFeedback + seller.NegativeFeedback + 1);

        double deliveryScore = Math.Min(Math.Log(1 + seller.SuccessfulDeliveries) / Math.Log(51), 1.0);

        double verificationScore = 0.0;
        if (seller.IsEmailVerified)   verificationScore += 0.15;
        if (seller.IsPhoneVerified)   verificationScore += 0.35;
        if (seller.IsAddressVerified) verificationScore += 0.50;

        double trust = (ageScore * 0.15)
                     + (feedbackScore * 0.40)
                     + (deliveryScore * 0.25)
                     + (verificationScore * 0.20);

        return Math.Clamp(trust, 0.0, 1.0);
    }
}
