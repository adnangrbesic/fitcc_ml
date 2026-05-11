using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Models;
using BuyGuardian.Api.Models.Requests;
using Pgvector;
using Pgvector.EntityFrameworkCore;

namespace BuyGuardian.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ListingsController : ControllerBase
{
    private readonly BuyGuardianContext _context;
    private readonly ILogger<ListingsController> _logger;

    public ListingsController(BuyGuardianContext context, ILogger<ListingsController> logger)
    {
        _context = context;
        _logger = logger;
    }

    [HttpGet]
    public async Task<ActionResult<IEnumerable<Listing>>> GetListings()
    {
        return await _context.Listings
            .OrderByDescending(l => l.ScrapedAt)
            .ToListAsync();
    }

    [HttpGet("unscored")]
    public async Task<ActionResult<IEnumerable<Listing>>> GetUnscoredListings()
    {
        return await _context.Listings
            .Where(l => l.TrustScore == null)
            .OrderByDescending(l => l.ScrapedAt)
            .ToListAsync();
    }

    [HttpPost("score-n")]
    public async Task<IActionResult> ScoreN([FromBody] ListingScoreNRequest request) 
    {
        if (!ModelState.IsValid)
        {
            _logger.LogWarning("ScoreN model state invalid: {Errors}", ModelState);
            return BadRequest(ModelState);
        }

        if (request?.Score == null || request.Score.Count == 0)
        {
            _logger.LogWarning("ScoreN request missing scores");
            return BadRequest("Missing score payload");
        }

        foreach (var kv in request.Score)
        {
            _context.Listings.Where(l => l.Id.ToString() == kv.Key).ExecuteUpdate(l => l.SetProperty(x => x.TrustScore, kv.Value));
        }

        return Ok();
    }

    [HttpGet("{id}")]
    public async Task<ActionResult<Listing>> GetListing(Guid id)
    {
        var listing = await _context.Listings
            .Include(l => l.Seller)
            .Include(l => l.PriceHistories)
            .FirstOrDefaultAsync(l => l.Id == id);

        if (listing == null)
        {
            return NotFound();
        }

        return listing;
    }

    [HttpGet("{itemId}/needs-enrichment")]
    public async Task<ActionResult<object>> NeedsEnrichment(string itemId)
    {
        var listing = await _context.Listings.FirstOrDefaultAsync(l => l.ItemId == itemId);
        
        if (listing == null)
        {
            return Ok(new { NeedsEnrichment = true, Reason = "Listing does not exist in DB." });
        }

        var ageHours = (DateTime.UtcNow - listing.ScrapedAt).TotalHours;
        if (ageHours > 24)
        {
            return Ok(new { NeedsEnrichment = true, Reason = $"Listing is older than 24h ({ageHours:F1}h)." });
        }

        return Ok(new { NeedsEnrichment = false, Reason = $"Listing was scraped recently ({ageHours:F1}h ago)." });
    }

    /// <summary>
    /// 3-Tier Lite Recommender:
    ///   1. Price Peer      — similar product, price within ±5%
    ///   2. Value Upgrade   — slightly more expensive (+5% to +25%), better specs
    ///   3. Budget Saver    — cheaper alternative (-10% to -30%), still trusted
    ///
    /// Uses pgvector cosine similarity on ProductVector for fast category matching,
    /// and percentage-based price ranges so it scales from phones to cars.
    /// </summary>
    [HttpGet("{itemId}/recommendations")]
    public async Task<ActionResult<List<RecommendationDto>>> GetRecommendations(string itemId)
    {
        // 1. Resolve the target listing + product
        var target = await _context.Listings
            .Include(l => l.Product)
            .Include(l => l.Seller)
            .FirstOrDefaultAsync(l => l.ItemId == itemId);

        if (target == null)
            return NotFound(new { Message = $"Listing {itemId} not found." });

        if (target.Product?.ProductVector == null)
            return Ok(new List<RecommendationDto>()); // No product vector → can't recommend

        var targetPrice = (double)target.Price;
        if (targetPrice <= 0)
            return Ok(new List<RecommendationDto>());

        var targetVector = target.Product.ProductVector;
        var targetProductId = target.ProductId;

        // 2. Find similar products via pgvector (cosine distance < 0.40 → ~60% similarity)
        //    This is intentionally broader than the 92% dedup threshold (0.08)
        //    so we pick up related but different products (e.g. iPhone 15 → iPhone 14, Galaxy S24)
        var similarProducts = await _context.Products
            .Where(p => p.ProductVector != null && p.Id != targetProductId)
            .OrderBy(p => p.ProductVector!.CosineDistance(targetVector))
            .Where(p => p.ProductVector!.CosineDistance(targetVector) < 0.40)
            .Select(p => p.Id)
            .Take(30) // Top 30 similar products is sufficient
            .ToListAsync();

        if (!similarProducts.Any())
            return Ok(new List<RecommendationDto>());

        // 3. Fetch candidate listings from those products (active, with seller trust)
        const double minSellerTrust = 0.40; // Only recommend trusted sellers
        var candidates = await _context.Listings
            .Include(l => l.Seller)
            .Include(l => l.Product)
            .Where(l => l.IsActive
                     && l.ItemId != itemId
                     && similarProducts.Contains(l.ProductId!.Value)
                     && l.Seller != null
                     && l.Seller.TrustScore >= minSellerTrust)
            .Select(l => new
            {
                l.ItemId,
                l.Title,
                l.Price,
                l.TrustScore,
                SellerTrust = l.Seller!.TrustScore,
                SellerName = l.Seller.Username,
                ProductName = l.Product!.CanonicalName,
                ProductAttrs = l.Product.Attributes,
                CosineDistance = l.Product.ProductVector!.CosineDistance(targetVector)
            })
            .OrderBy(l => l.CosineDistance)
            .Take(100) // Cap candidates for efficiency
            .ToListAsync();

        if (!candidates.Any())
            return Ok(new List<RecommendationDto>());

        // 4. Extract target product specs for upgrade comparison
        int targetStorage = ExtractIntAttr(target.Product.Attributes, "storage_gb");
        int targetRam = ExtractIntAttr(target.Product.Attributes, "ram_gb");

        var recommendations = new List<RecommendationDto>();

        // ── Price Peer: within ±5% of target price ──────────────────────
        var pricePeer = candidates
            .Where(c => Math.Abs((double)c.Price - targetPrice) / targetPrice <= 0.05)
            .OrderBy(c => c.CosineDistance)
            .ThenByDescending(c => c.SellerTrust)
            .FirstOrDefault();

        if (pricePeer != null)
        {
            var diff = ((double)pricePeer.Price - targetPrice) / targetPrice * 100;
            recommendations.Add(new RecommendationDto(
                pricePeer.ItemId,
                pricePeer.Title,
                pricePeer.Price,
                pricePeer.SellerTrust,
                pricePeer.SellerName,
                pricePeer.ProductName,
                "price_peer",
                $"Slična cijena ({diff:+0.0;-0.0}%)",
                "Oglas u istom cjenovnom rangu sa pouzdanim prodavačem."
            ));
        }

        // ── Value Upgrade: +5% to +25%, better specs ────────────────────
        var upgrade = candidates
            .Where(c =>
            {
                var priceDiff = ((double)c.Price - targetPrice) / targetPrice;
                if (priceDiff < 0.05 || priceDiff > 0.25) return false;

                // CRITICAL FIX: Exclude products that are extremely identical via vector distance
                // This prevents recommending the same product that has slightly different canonical name.
                // 0.08 is our dedup threshold. Anything < 0.08 is effectively the exact same item.
                if (c.CosineDistance < 0.08) return false;

                // Also prevent exact case-insensitive name overlaps (iPhone 15 -> iPhone 15)
                if (c.ProductName.Equals(target.Product.CanonicalName, StringComparison.OrdinalIgnoreCase))
                    return false;

                // Check if specs are actually better
                int cStorage = ExtractIntAttr(c.ProductAttrs, "storage_gb");
                int cRam = ExtractIntAttr(c.ProductAttrs, "ram_gb");
                bool hasBetterSpecs = (cStorage > targetStorage && targetStorage > 0)
                                   || (cRam > targetRam && targetRam > 0);
                return hasBetterSpecs;
            })
            .OrderByDescending(c =>
            {
                // Score: prioritize better specs with smaller price increase
                int cStorage = ExtractIntAttr(c.ProductAttrs, "storage_gb");
                int cRam = ExtractIntAttr(c.ProductAttrs, "ram_gb");
                double specGain = 0;
                if (targetStorage > 0) specGain += (double)(cStorage - targetStorage) / targetStorage;
                if (targetRam > 0) specGain += (double)(cRam - targetRam) / targetRam;
                double pricePenalty = ((double)c.Price - targetPrice) / targetPrice;
                return specGain - pricePenalty; // Higher is better
            })
            .ThenByDescending(c => c.SellerTrust)
            .FirstOrDefault();

        if (upgrade != null)
        {
            var diff = ((double)upgrade.Price - targetPrice) / targetPrice * 100;
            int uStorage = ExtractIntAttr(upgrade.ProductAttrs, "storage_gb");
            int uRam = ExtractIntAttr(upgrade.ProductAttrs, "ram_gb");
            var specDetails = new List<string>();
            if (uStorage > targetStorage && targetStorage > 0) specDetails.Add($"{uStorage}GB memorije");
            if (uRam > targetRam && targetRam > 0) specDetails.Add($"{uRam}GB RAM-a");
            var specText = specDetails.Any() ? string.Join(", ", specDetails) : "bolje karakteristike";

            recommendations.Add(new RecommendationDto(
                upgrade.ItemId,
                upgrade.Title,
                upgrade.Price,
                upgrade.SellerTrust,
                upgrade.SellerName,
                upgrade.ProductName,
                "value_upgrade",
                $"Bolje karakteristike (+{diff:0.0}%)",
                $"Ima {specText} za samo {diff:0.0}% višu cijenu."
            ));
        }

        // ── Budget Saver: -10% to -30% cheaper ─────────────────────────
        var budget = candidates
            .Where(c =>
            {
                var priceDiff = (targetPrice - (double)c.Price) / targetPrice;
                return priceDiff >= 0.10 && priceDiff <= 0.30;
            })
            .OrderByDescending(c => c.SellerTrust) // Prioritize most trusted
            .ThenBy(c => c.CosineDistance) // Then most similar product
            .FirstOrDefault();

        if (budget != null)
        {
            var savings = (targetPrice - (double)budget.Price) / targetPrice * 100;
            recommendations.Add(new RecommendationDto(
                budget.ItemId,
                budget.Title,
                budget.Price,
                budget.SellerTrust,
                budget.SellerName,
                budget.ProductName,
                "budget_saver",
                $"Uštedi {savings:0.0}%",
                $"Sličan proizvod za {savings:0.0}% nižu cijenu sa pouzdanim prodavačem."
            ));
        }

        return Ok(recommendations);
    }

    /// <summary>Extract an integer attribute from product JSONB attributes.</summary>
    private static int ExtractIntAttr(Dictionary<string, object>? attrs, string key)
    {
        if (attrs == null || !attrs.TryGetValue(key, out var val)) return 0;
        if (val is System.Text.Json.JsonElement je)
        {
            if (je.TryGetInt32(out var i)) return i;
            if (je.TryGetDouble(out var d)) return (int)d;
        }
        if (int.TryParse(val?.ToString(), out var result)) return result;
        return 0;
    }
}

/// <summary>
/// A single recommendation card returned to the extension.
/// </summary>
public record RecommendationDto(
    string ItemId,
    string Title,
    decimal Price,
    double SellerTrust,
    string SellerName,
    string ProductName,
    string Type,       // "price_peer" | "value_upgrade" | "budget_saver"
    string Badge,      // Short label for UI chip
    string Reason      // Explanation sentence
);
