using MediatR;
using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Interfaces;
using System.Text.Json;

namespace BuyGuardian.Api.Features;

public class AnalyzeListingHandler : IRequestHandler<AnalyzeListingQuery, ListingAnalysisResult>
{
    private readonly BuyGuardianContext _context;
    private readonly ICacheService _cache;

    public AnalyzeListingHandler(BuyGuardianContext context, ICacheService cache)
    {
        _context = context;
        _cache = cache;
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

        // Compute TrustScore (existing logic)
        double trustScore = 0.5; // Base score
        
        if (listing.Seller != null)
        {
            trustScore += listing.Seller.TrustScore * 0.3;
        }

        if (listing.PriceHistories.Count > 1)
        {
            var prices = listing.PriceHistories.Select(p => (double)p.Price).ToList();
            var stdDev = CalculateStandardDeviation(prices);
            var avg = prices.Average();
            
            if (avg > 0)
            {
                var volatility = stdDev / avg;
                trustScore += (1.0 - Math.Min(volatility, 1.0)) * 0.4;
            }
        }
        else
        {
            trustScore += 0.2;
        }

        if (listing.RawMetadata.TryGetValue("context", out var contextObj) && contextObj is JsonElement contextElem)
        {
            if (contextElem.TryGetProperty("condition", out var conditionElem) && conditionElem.TryGetDouble(out var condition))
            {
                trustScore += condition * 0.3;
            }
        }
        else
        {
            trustScore += 0.15;
        }

        listing.TrustScore = Math.Clamp(trustScore, 0.0, 1.0);
        await _context.SaveChangesAsync(cancellationToken);

        var isSuspicious = listing.TrustScore < 0.4;
        
        // Extract richer data
        var risks = new List<string>();
        if (isSuspicious) risks.Add("low_trust");
        if (listing.PriceHistories.Count < 2) risks.Add("new_listing");
        if (listing.Seller?.AccountAgeMonths < 3) risks.Add("new_account");

        int? warranty = null;
        if (listing.RawMetadata.TryGetValue("context", out var ctx) && ctx is JsonElement ctxElem)
        {
            if (ctxElem.TryGetProperty("warranty_months", out var wElem) && wElem.TryGetInt32(out var w))
                warranty = w;
        }

        var result = new ListingAnalysisResult(
            listing.ItemId,
            listing.Title,
            listing.TrustScore.Value * 10, // UI expects 0-10
            $"Analiza za {listing.Title}. Trust: {listing.TrustScore:P0}.",
            isSuspicious,
            listing.Product?.AvgPrice ?? listing.Price,
            listing.Price,
            risks.ToArray(),
            listing.Seller?.TrustScore ?? 0.5,
            listing.Product?.CategoryName,
            listing.Product?.CanonicalName,
            warranty
        );

        await _cache.SetAsync(cacheKey, result, TimeSpan.FromHours(1));

        return result;
    }

    private double CalculateStandardDeviation(IEnumerable<double> values)
    {
        double avg = values.Average();
        return Math.Sqrt(values.Average(v => Math.Pow(v - avg, 2)));
    }
}
