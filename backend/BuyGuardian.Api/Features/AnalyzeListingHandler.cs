using MediatR;
using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Interfaces;

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
            .FirstOrDefaultAsync(l => l.Id == request.ListingId, cancellationToken);

        if (listing == null)
            throw new KeyNotFoundException($"Listing {request.ListingId} not found");

        // Simple analysis logic for demonstration
        var isSuspicious = listing.Seller?.TrustScore < 0.5 || (listing.TrustScore.HasValue && listing.TrustScore < 0.3);
        var summary = $"Listing analyzed. Seller: {listing.Seller?.Username ?? "Unknown"}. " +
                      $"Product: {listing.Product?.CanonicalName ?? "Unknown"}. " +
                      $"Suspicious: {isSuspicious}";

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
}
