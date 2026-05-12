using MediatR;
using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Features;

public record AnalyzeListingQuery(string ItemId) : IRequest<ListingAnalysisResult>;

public record ListingAnalysisResult(
    string ItemId,
    string Title,
    double TrustScore,
    double OverallScore,
    string AnalysisSummary,
    bool IsSuspicious,
    decimal MarketPrice,
    decimal? ListingPrice,
    string[] Risks,
    double SellerTrust,
    bool IsNewSeller,
    string? Category,
    string? ProductName,
    int? WarrantyMonths,
    // Isolation Forest anomaly detection
    double? AnomalyScore,
    bool? IsAnomaly,
    string? AnomalyType,
    // Seller Details for transparent UI stats
    int? PositiveFeedback,
    int? NegativeFeedback,
    int? SuccessfulDeliveries,
    int? AccountAgeMonths,
    // Target comparative price point
    string? CheapestItemId,
    decimal? CheapestPrice,
    string? CheapestTitle,
    string? CheapestSellerName
);
