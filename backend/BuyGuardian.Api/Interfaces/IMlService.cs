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
    /// Score all active listings for a product in one batch.
    /// </summary>
    Task<List<AnomalyResult>?> GetAnomalyScoreBatchAsync(Guid productId);

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

    /// <summary>
    /// Trigger CatBoost retraining with admin-labeled ground truth data.
    /// Labels indicate which listings are trusted/suspicious.
    /// listingsMap provides full Listing entities for feature extraction.
    /// This breaks the rule→model→rule loop.
    /// </summary>
    Task<RetrainFromLabelsResult?> TriggerTrustScoreRetrainWithLabelsAsync(
        List<(string ItemId, string Label)> labels,
        Dictionary<string, Listing> listingsMap);
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

/// <summary>
/// Response from the labeled retrain endpoint.
/// </summary>
public record RetrainFromLabelsResult(
    string Status,
    int LabelsUsed,
    string ModelPath
);
