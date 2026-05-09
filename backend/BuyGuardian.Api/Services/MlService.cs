using System.Text.Json;
using System.Text.Json.Serialization;
using BuyGuardian.Api.Interfaces;

namespace BuyGuardian.Api.Services;

/// <summary>
/// HTTP client that communicates with the Python ML microservice
/// for Isolation Forest anomaly detection.
/// 
/// Designed for resilience: all calls have timeouts, and failures
/// return null / are logged rather than crashing the API.
/// </summary>
public class MlService : IMlService
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<MlService> _logger;

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    public MlService(HttpClient httpClient, ILogger<MlService> logger)
    {
        _httpClient = httpClient;
        _httpClient.BaseAddress ??= new Uri("http://ml-service:8000");
        _httpClient.Timeout = TimeSpan.FromSeconds(30);
        _logger = logger;
    }

    public async Task<AnomalyResult?> GetAnomalyScoreAsync(string itemId)
    {
        try
        {
            var response = await _httpClient.PostAsync($"/api/anomaly/score/{itemId}", null);
            
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning(
                    "ML service returned {StatusCode} for item {ItemId}",
                    response.StatusCode, itemId);
                return null;
            }

            var json = await response.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<AnomalyResult>(json, JsonOpts);
        }
        catch (TaskCanceledException)
        {
            _logger.LogWarning("ML service request timed out for item {ItemId}", itemId);
            return null;
        }
        catch (HttpRequestException ex)
        {
            _logger.LogWarning(ex, "ML service unavailable when scoring item {ItemId}", itemId);
            return null;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error calling ML service for item {ItemId}", itemId);
            return null;
        }
    }

    public async Task TriggerRetrainAsync(Guid productId)
    {
        try
        {
            var content = new StringContent(
                JsonSerializer.Serialize(new { product_id = productId.ToString() }),
                System.Text.Encoding.UTF8,
                "application/json");

            var response = await _httpClient.PostAsync("/api/anomaly/retrain", content);
            
            if (response.IsSuccessStatusCode)
            {
                _logger.LogInformation("ML retrain triggered for product {ProductId}", productId);
            }
            else
            {
                _logger.LogWarning(
                    "ML retrain returned {StatusCode} for product {ProductId}",
                    response.StatusCode, productId);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to trigger ML retrain for product {ProductId}", productId);
        }
    }
}
