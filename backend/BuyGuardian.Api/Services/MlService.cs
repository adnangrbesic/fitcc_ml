using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using BuyGuardian.Api.Interfaces;
using BuyGuardian.Api.Models;
using BuyGuardian.Api.Models.Requests;

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
    private readonly string _trustScoreBaseUrl;

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    public MlService(HttpClient httpClient, ILogger<MlService> logger, IConfiguration configuration)
    {
        _httpClient = httpClient;
        var anomalyBase = configuration["MlService:BaseUrl"] ?? "http://ml-service:8000";
        _httpClient.BaseAddress ??= new Uri(anomalyBase);
        _httpClient.Timeout = TimeSpan.FromSeconds(30);
        _logger = logger;
        _trustScoreBaseUrl = (configuration["TrustScoreService:BaseUrl"]
            ?? "http://ml-service-listing:8010").TrimEnd('/');
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

    public async Task<TrustScoreResult?> GetTrustScoreAsync(Listing listing, bool retrain = true)
    {
        try
        {
            var request = new TrustScoreRequest
            {
                Listing = TrustScoreListingPayload.FromListing(listing),
                Retrain = retrain,
            };

            var payload = JsonSerializer.Serialize(request, JsonOpts);
            var content = new StringContent(payload, Encoding.UTF8, "application/json");
            var url = $"{_trustScoreBaseUrl}/api/trust-score/predict";

            var response = await _httpClient.PostAsync(url, content);
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning(
                    "Trust score service returned {StatusCode} for listing {ItemId}",
                    response.StatusCode,
                    listing.ItemId);
                return null;
            }

            var json = await response.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<TrustScoreResult>(json, JsonOpts);
        }
        catch (TaskCanceledException)
        {
            _logger.LogWarning("Trust score request timed out for item {ItemId}", listing.ItemId);
            return null;
        }
        catch (HttpRequestException ex)
        {
            _logger.LogWarning(ex, "Trust score service unavailable for item {ItemId}", listing.ItemId);
            return null;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error calling trust score service for item {ItemId}", listing.ItemId);
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

    public async Task<TrustScoreRetrainResult?> TriggerTrustScoreFullRetrainAsync()
    {
        try
        {
            var url = $"{_trustScoreBaseUrl}/api/trust-score/retrain-full";
            var response = await _httpClient.PostAsync(url, null);
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning(
                    "Trust score retrain returned {StatusCode}",
                    response.StatusCode);
                return null;
            }

            var json = await response.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<TrustScoreRetrainResult>(json, JsonOpts);
        }
        catch (TaskCanceledException)
        {
            _logger.LogWarning("Trust score retrain request timed out");
            return null;
        }
        catch (HttpRequestException ex)
        {
            _logger.LogWarning(ex, "Trust score service unavailable for retrain");
            return null;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error calling trust score retrain");
            return null;
        }
    }
}
