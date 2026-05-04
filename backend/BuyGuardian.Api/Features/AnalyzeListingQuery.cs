using MediatR;
using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Features;

public record AnalyzeListingQuery(string ItemId) : IRequest<ListingAnalysisResult>;

public record ListingAnalysisResult(
    string ItemId,
    string Title,
    double TrustScore,
    string AnalysisSummary,
    bool IsSuspicious,
    decimal MarketPrice,
    decimal? ListingPrice,
    string[] Risks,
    double SellerTrust,
    string? Category,
    string? ProductName,
    int? WarrantyMonths
);
