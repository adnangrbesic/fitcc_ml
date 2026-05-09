using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Interfaces;

/// <summary>
/// Client interface for the Python ML anomaly detection microservice.
/// </summary>
public interface IMlService
{
    /// <summary>
    /// Score a single listing for price anomaly via the Isolation Forest model.
    /// Returns null if the ML service is unavailable or the listing has no linked product.
    /// </summary>
    Task<AnomalyResult?> GetAnomalyScoreAsync(string itemId);

    /// <summary>
    /// Predict trust score for a listing via the trust score service.
    /// Returns null if the service is unavailable or the payload is rejected.
    /// </summary>
    Task<TrustScoreResult?> GetTrustScoreAsync(Listing listing, bool retrain = true);

    /// <summary>
    /// Trigger model retraining for a specific product group.
    /// Fire-and-forget; failures are logged but not propagated.
    /// </summary>
    Task TriggerRetrainAsync(Guid productId);

    /// <summary>
    /// Trigger full retrain of the trust score model from its dataset.
    /// Returns null if the trust score service is unavailable.
    /// </summary>
    Task<TrustScoreRetrainResult?> TriggerTrustScoreFullRetrainAsync();
}

/// <summary>
/// Response from the ML service anomaly scoring endpoint.
/// </summary>
public record AnomalyResult(
    string ItemId,
    string? ProductId,
    double AnomalyScore,
    bool IsAnomaly,
    string? AnomalyType,
    Dictionary<string, double> Features,
    string Confidence,
    double ProductMedianPrice,
    int ProductListingCount,
    string Method
);

/// <summary>
/// Response from the ML trust score service.
/// </summary>
public record TrustScoreResult(
    string ListingId,
    double TrustScore,
    double Confidence,
    string[] Reasons,
    bool ModelUsed
);

/// <summary>
/// Response from the trust score full retrain endpoint.
/// </summary>
public record TrustScoreRetrainResult(
    string Status,
    int Rows,
    string ModelPath
);
