using MediatR;
using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Features;

/// <summary>MediatR query to request analysis for a specific OLX listing.</summary>
public record AnalyzeListingQuery(string ItemId) : IRequest<ListingAnalysisResult>;

/// <summary>
/// Full analysis result returned to the Chrome extension.
/// Contains trust scores, anomaly flags, seller stats, market price comparison,
/// and product attributes for dynamic comparison rendering.
/// </summary>
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
    Dictionary<string, object>? Attributes,
    /// <summary>True when the listing has too little data for meaningful analysis.</summary>
    bool HasInsufficientData,
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
    string? CheapestSellerName,
    string[] UiAlerts
);
