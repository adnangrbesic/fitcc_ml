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
    /// Trigger model retraining for a specific product group.
    /// Fire-and-forget; failures are logged but not propagated.
    /// </summary>
    Task TriggerRetrainAsync(Guid productId);
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
