using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Models;
using BuyGuardian.Api.Models.Requests;

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
}
