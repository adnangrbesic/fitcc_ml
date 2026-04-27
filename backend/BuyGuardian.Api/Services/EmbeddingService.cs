using System.Net.Http.Json;
using System.Text.Json.Serialization;
using Pgvector;
using Microsoft.Extensions.Configuration;

namespace BuyGuardian.Api.Services;

public interface IEmbeddingService
{
    Task<Vector> GetEmbeddingAsync(string text);
}

public class EmbeddingService : IEmbeddingService
{
    private readonly HttpClient _httpClient;
    private readonly IConfiguration _configuration;
    private readonly string _model;

    public EmbeddingService(HttpClient httpClient, IConfiguration configuration)
    {
        _httpClient = httpClient;
        _configuration = configuration;
        _model = _configuration["Ollama:EmbeddingModel"] ?? "nomic-embed-text";
        
        var baseUrl = _configuration["Ollama:BaseUrl"] ?? "http://localhost:11434";
        _httpClient.BaseAddress = new Uri(baseUrl);
    }

    public async Task<Vector> GetEmbeddingAsync(string text)
    {
        var response = await _httpClient.PostAsJsonAsync("api/embed", new
        {
            model = _model,
            input = text // Ollama /api/embed uses 'input' instead of 'prompt'
        });

        if (!response.IsSuccessStatusCode)
        {
            var errorBody = await response.Content.ReadAsStringAsync();
            throw new Exception($"Ollama error ({response.StatusCode}): {errorBody}");
        }

        var result = await response.Content.ReadFromJsonAsync<OllamaEmbedResponse>();
        
        if (result?.Embeddings == null || result.Embeddings.Length == 0)
            throw new Exception("Failed to get embedding from Ollama");

        return new Vector(result.Embeddings[0].Select(f => (float)f).ToArray());
    }

    private class OllamaEmbedResponse
    {
        [JsonPropertyName("embeddings")]
        public double[][]? Embeddings { get; set; }
    }
}
