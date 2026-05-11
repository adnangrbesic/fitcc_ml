using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using StackExchange.Redis;

namespace BuyGuardian.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ScrapeController : ControllerBase
{
    private readonly IDatabase _redis;
    private readonly ILogger<ScrapeController> _logger;
    private readonly BuyGuardian.Api.Data.BuyGuardianContext _db;
    private const string QueueName = "olx:urls";
    private const string RawQueueName = "olx:raw_listings";

    public ScrapeController(
        IConnectionMultiplexer redisMuxer, 
        ILogger<ScrapeController> logger,
        BuyGuardian.Api.Data.BuyGuardianContext db)
    {
        _redis = redisMuxer.GetDatabase();
        _logger = logger;
        _db = db;
    }

    [HttpPost("queue")]
    public async Task<IActionResult> QueueUrl([FromBody] string url)
    {
        if (string.IsNullOrEmpty(url)) return BadRequest("URL is required");

        _logger.LogInformation("Adding URL to scrape queue: {Url}", url);
        await _redis.KeyDeleteAsync("olx:stop_requested");
        await _redis.ListLeftPushAsync(QueueName, url);
        return Ok(new { Message = "URL added to queue", Queue = QueueName, Url = url });
    }

    [HttpPost("queue-batch")]
    public async Task<IActionResult> QueueBatch([FromBody] string[] urls)
    {
        if (urls == null || urls.Length == 0) return BadRequest("URLs are required");

        await _redis.KeyDeleteAsync("olx:stop_requested");
        foreach (var url in urls)
        {
            await _redis.ListLeftPushAsync(QueueName, url);
        }
        
        return Ok(new { Message = $"{urls.Length} URLs added to queue" });
    }

    [HttpPost("category")]
    public async Task<IActionResult> QueueCategory([FromBody] CategoryScrapeRequest request)
    {
        if (string.IsNullOrEmpty(request.Url)) return BadRequest("URL is required");

        _logger.LogInformation("Adding Category URL to scrape queue: {Url} (MaxPages: {MaxPages}, Page: {Page})", request.Url, request.MaxPages, request.Page);
        
        await _redis.KeyDeleteAsync("olx:stop_requested");

        if (request.Page.HasValue && request.Page.Value > 0)
        {
            var message = System.Text.Json.JsonSerializer.Serialize(request);
            await _redis.ListLeftPushAsync("olx:category_tasks", message);
            return Ok(new { Message = $"Category page {request.Page} added to queue", Queue = "olx:category_tasks", Data = request });
        }
        else
        {
            int pagesToQueue = request.MaxPages > 0 ? request.MaxPages : 5;
            _logger.LogInformation("Splitting category task into {PagesToQueue} individual page tasks.", pagesToQueue);

            for (int p = 1; p <= pagesToQueue; p++)
            {
                var pageRequest = new CategoryScrapeRequest
                {
                    Url = request.Url,
                    MaxPages = request.MaxPages,
                    Page = p
                };
                var message = System.Text.Json.JsonSerializer.Serialize(pageRequest);
                await _redis.ListLeftPushAsync("olx:category_tasks", message);
            }

            return Ok(new { Message = $"{pagesToQueue} category pages added to queue as separate tasks", Queue = "olx:category_tasks" });
        }
    }

    [HttpDelete("queue")]
    public async Task<IActionResult> ClearQueues()
    {
        _logger.LogWarning("Clearing all scrape queues and requesting workers to stop.");
        
        // Remove the lists
        await _redis.KeyDeleteAsync("olx:urls");
        await _redis.KeyDeleteAsync("olx:category_tasks");
        
        // Request active sequential loops to stop early
        await _redis.StringSetAsync("olx:stop_requested", "true", TimeSpan.FromMinutes(5));
        
        return Ok(new { Message = "Scrape queues cleared successfully. Workers will stop their current items and exit early." });
    }

    /// <summary>
    /// Maintenance endpoint to re-enrich ALL existing database listings with newest prompts.
    /// Reads DB state and publishes straight back to the python raw enrichment queue.
    /// </summary>
    [HttpPost("re-enrich-all")]
    public async Task<IActionResult> RequeueAllForEnrichment([FromQuery] int limit = 500)
    {
        _logger.LogInformation("Initiating maintenance: Re-enriching historical listings (Limit: {Limit})", limit);
        
        // 1. Fetch target active listings including needed data
        var listings = await Microsoft.EntityFrameworkCore.EntityFrameworkQueryableExtensions.ToListAsync(
            _db.Listings
                .Include(l => l.Seller)
                .Where(l => l.IsActive)
                .OrderByDescending(l => l.ScrapedAt)
                .Take(limit)
        );

        if (!listings.Any()) return Ok(new { Count = 0, Message = "No active listings found to enrich." });

        int queued = 0;
        foreach (var listing in listings)
        {
            try 
            {
                // Rebuild python ListingData contract format
                string breadcrumbs = "";
                object rawSpecs = new Dictionary<string, string>();

                if (listing.RawMetadata != null)
                {
                    if (listing.RawMetadata.TryGetValue("breadcrumbs", out var b) && b != null) breadcrumbs = b.ToString() ?? "";
                    if (listing.RawMetadata.TryGetValue("raw_specs", out var s) && s != null) rawSpecs = s;
                }

                var pythonPayload = new
                {
                    item_id = listing.ItemId,
                    title = listing.Title,
                    price = (double)listing.Price,
                    currency = "KM",
                    seller_id = listing.Seller?.OlxId ?? "nepoznato",
                    seller_name = listing.Seller?.Username ?? "Nepoznato",
                    is_email_verified = listing.Seller?.IsEmailVerified ?? false,
                    is_phone_verified = listing.Seller?.IsPhoneVerified ?? false,
                    is_address_verified = listing.Seller?.IsAddressVerified ?? false,
                    positive_feedback = listing.Seller?.PositiveFeedback ?? 0,
                    neutral_feedback = listing.Seller?.NeutralFeedback ?? 0,
                    negative_feedback = listing.Seller?.NegativeFeedback ?? 0,
                    successful_deliveries = listing.Seller?.SuccessfulDeliveries ?? 0,
                    account_age_months = listing.Seller?.AccountAgeMonths ?? 0,
                    description = listing.Description ?? "",
                    is_active = listing.IsActive,
                    is_new = listing.IsNew,
                    breadcrumbs = breadcrumbs,
                    raw_specs = rawSpecs,
                    scraped_at = listing.ScrapedAt.ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                    last_seen_at = System.DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
                };

                string json = System.Text.Json.JsonSerializer.Serialize(pythonPayload);
                await _redis.ListLeftPushAsync(RawQueueName, json);
                queued++;
            }
            catch (System.Exception ex)
            {
                _logger.LogError(ex, "Failed to map/requeue item {ItemId}", listing.ItemId);
            }
        }

        return Ok(new 
        { 
            Count = queued, 
            Message = $"Successfully pushed {queued} existing records into enrichment pipeline.",
            Queue = RawQueueName
        });
    }
}

public class CategoryScrapeRequest
{
    public string Url { get; set; } = string.Empty;
    public int MaxPages { get; set; } = 0; // 0 means infinite
    public int? Page { get; set; }
}
