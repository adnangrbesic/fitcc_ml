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
        var cacheKey = $"analysis:{request.ListingId}";
        var cached = await _cache.GetAsync<ListingAnalysisResult>(cacheKey);
        if (cached != null) return cached;

        var listing = await _context.Listings
            .Include(l => l.Seller)
            .Include(l => l.Product)
            .Include(l => l.PriceHistories)
            .FirstOrDefaultAsync(l => l.Id == request.ListingId, cancellationToken);

        if (listing == null)
            throw new KeyNotFoundException($"Listing {request.ListingId} not found");

        // Compute TrustScore
        double trustScore = 0.5; // Base score
        
        // 1. Seller Trust (0.3 weight)
        if (listing.Seller != null)
        {
            trustScore += listing.Seller.TrustScore * 0.3;
        }

        // 2. Price Stability (0.4 weight)
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
            trustScore += 0.2; // Neutral for single data point
        }

        // 3. Condition/Metadata (0.3 weight)
        if (listing.RawMetadata.TryGetValue("condition_score", out var scoreObj) && scoreObj is JsonElement scoreElem && scoreElem.TryGetDouble(out var score))
        {
            trustScore += score * 0.3;
        }
        else
        {
            trustScore += 0.15; // Neutral
        }

        // Final normalization and update DB
        listing.TrustScore = Math.Clamp(trustScore, 0.0, 1.0);
        await _context.SaveChangesAsync(cancellationToken);

        var isSuspicious = listing.TrustScore < 0.4;
        var summary = $"Trust Analysis: {listing.TrustScore:P0}. " +
                      $"Seller: {listing.Seller?.Username ?? "N/A"}. " +
                      $"Price History: {listing.PriceHistories.Count} records. " +
                      $"Condition Score: {scoreObj ?? "N/A"}. " +
                      $"Status: {(isSuspicious ? "⚠️ Suspicious" : "✅ Verified")}";

        var result = new ListingAnalysisResult(
            listing.Id,
            listing.Title,
            listing.TrustScore,
            summary,
            isSuspicious
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
