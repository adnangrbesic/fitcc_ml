using MediatR;
using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Features;

public record AnalyzeListingQuery(Guid ListingId) : IRequest<ListingAnalysisResult>;

public record ListingAnalysisResult(
    Guid ListingId,
    string Title,
    double? TrustScore,
    string AnalysisSummary,
    bool IsSuspicious
);
