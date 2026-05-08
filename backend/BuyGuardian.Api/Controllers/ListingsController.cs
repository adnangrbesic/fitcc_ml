using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ListingsController : ControllerBase
{
    private readonly BuyGuardianContext _context;

    public ListingsController(BuyGuardianContext context)
    {
        _context = context;
    }

    [HttpGet]
    public async Task<ActionResult<IEnumerable<Listing>>> GetListings()
    {
        return await _context.Listings
            .Include(l => l.Seller)
            .OrderByDescending(l => l.ScrapedAt)
            .ToListAsync();
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
