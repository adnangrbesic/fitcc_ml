using BuyGuardian.Api.Data;
using BuyGuardian.Api.Models;
using Microsoft.EntityFrameworkCore;
using Pgvector;
using Pgvector.EntityFrameworkCore;
using StackExchange.Redis;
using System.Text.Json;

namespace BuyGuardian.Api.Services;

public interface IProductMatcher
{
    Task<Guid?> MatchProductAsync(BuyGuardianContext db, string canonicalName, double confidence);
}

public class ProductMatcher : IProductMatcher
{
    private readonly IEmbeddingService _embeddingService;
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<ProductMatcher> _logger;

    public ProductMatcher(IEmbeddingService embeddingService, IConnectionMultiplexer redis, ILogger<ProductMatcher> logger)
    {
        _embeddingService = embeddingService;
        _redis = redis;
        _logger = logger;
    }

    public async Task<Guid?> MatchProductAsync(BuyGuardianContext db, string canonicalName, double confidence)
    {
        if (string.IsNullOrWhiteSpace(canonicalName)) return null;
        
        // 0. LLM Confidence Check (The "Learning" System)
        if (confidence < 0.80)
        {
            _logger.LogWarning("Low LLM confidence ({Confidence}) for: {Canonical}. Pushing to review queue.", confidence, canonicalName);
            await PushToReviewQueue(canonicalName, new List<string> { "Low LLM Confidence" });
            return null; // Force manual review, do not match automatically
        }

        // 1. pgvector cosine (95% hit)
        _logger.LogInformation("Attempting pgvector match for: {Canonical}", canonicalName);
        var embedding = await _embeddingService.GetEmbeddingAsync(canonicalName);
        
        var pgCandidates = await db.Products
            .OrderBy(p => p.ProductVector!.CosineDistance(embedding))
            .Where(p => p.ProductVector!.CosineDistance(embedding) < 0.08) // 92% similarity
            .Select(p => new { p.Id, p.CanonicalName })
            .Take(5)
            .ToListAsync();

        foreach (var cand in pgCandidates)
        {
            if (IsLogicalMatch(canonicalName, cand.CanonicalName))
            {
                _logger.LogInformation("pgvector verified logical match found: {Match}", cand.CanonicalName);
                return cand.Id;
            }
        }

        // 2. Fuzzy fallback (4% hit)
        _logger.LogInformation("pgvector failed. Attempting fuzzy match for: {Canonical}", canonicalName);
        var allProducts = await db.Products.Select(p => new { p.Id, p.CanonicalName }).ToListAsync();
        
        string canonicalLower = canonicalName.ToLowerInvariant();

        var fuzzyMatch = allProducts
            .Select(p => {
                bool isLogical = IsLogicalMatch(canonicalName, p.CanonicalName);
                
                return new { 
                    p.Id, 
                    Distance = isLogical ? ComputeLevenshteinDistance(canonicalLower, p.CanonicalName.ToLowerInvariant()) : 999 
                };
            })
            .Where(x => x.Distance < 3)
            .OrderBy(x => x.Distance)
            .FirstOrDefault();

        if (fuzzyMatch != null)
        {
            _logger.LogInformation("Fuzzy match found: {Id} (Dist: {Dist})", fuzzyMatch.Id, fuzzyMatch.Distance);
            return fuzzyMatch.Id;
        }

        // 3. Human Review (similarity 0.85-0.92)
        var closestDist = allProducts.Any() ? allProducts.Min(p => ComputeLevenshteinDistance(canonicalName.ToLowerInvariant(), p.CanonicalName.ToLowerInvariant())) : 99;
        
        if (closestDist < 10) // Arbitrary threshold for "almost" match
        {
            await PushToReviewQueue(canonicalName, allProducts.Take(5).Select(p => p.CanonicalName).ToList());
        }

        return null;
    }

    private static bool IsLogicalMatch(string canonical, string candidate)
    {
        if (string.IsNullOrWhiteSpace(canonical) || string.IsNullOrWhiteSpace(candidate)) return false;
        
        string a = canonical.ToLowerInvariant();
        string b = candidate.ToLowerInvariant();

        // 1. Strict Number Sequence Match
        var aNumbers = System.Text.RegularExpressions.Regex.Matches(a, @"\d+").Select(m => m.Value).OrderBy(n => n).ToList();
        var bNumbers = System.Text.RegularExpressions.Regex.Matches(b, @"\d+").Select(m => m.Value).OrderBy(n => n).ToList();
        
        if (!aNumbers.SequenceEqual(bNumbers))
            return false; // Block if number sequences differ (e.g., 128 != 256, or A16 != A37)

        // 2. Critical Model Suffix Checks
        var criticalSuffixes = new[] { "plus", "pro", "max", "ultra", "mini", "lite", "neo", "active", "fe" };
        foreach (var suffix in criticalSuffixes)
        {
            bool hasA = System.Text.RegularExpressions.Regex.IsMatch(a, $@"\b{suffix}\b");
            bool hasB = System.Text.RegularExpressions.Regex.IsMatch(b, $@"\b{suffix}\b");
            
            if (hasA != hasB)
                return false; // One string has the special model suffix, the other doesn't!
        }

        return true;
    }

    private async Task PushToReviewQueue(string canonical, List<string> candidates)
    {
        var db = _redis.GetDatabase();
        var payload = JsonSerializer.Serialize(new { canonical, candidates, timestamp = DateTime.UtcNow });
        await db.ListLeftPushAsync("review_products", payload);
        _logger.LogWarning("Product pushed to human review: {Canonical}", canonical);
    }

    private static int ComputeLevenshteinDistance(string s, string t)
    {
        if (string.IsNullOrEmpty(s)) return string.IsNullOrEmpty(t) ? 0 : t.Length;
        if (string.IsNullOrEmpty(t)) return s.Length;

        int n = s.Length;
        int m = t.Length;
        int[,] d = new int[n + 1, m + 1];

        for (int i = 0; i <= n; d[i, 0] = i++) ;
        for (int j = 0; j <= m; d[0, j] = j++) ;

        for (int i = 1; i <= n; i++)
        {
            for (int j = 1; j <= m; j++)
            {
                int cost = (t[j - 1] == s[i - 1]) ? 0 : 1;
                d[i, j] = Math.Min(Math.Min(d[i - 1, j] + 1, d[i, j - 1] + 1), d[i - 1, j - 1] + cost);
            }
        }
        return d[n, m];
    }
}
