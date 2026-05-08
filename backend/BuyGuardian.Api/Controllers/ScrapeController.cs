using Microsoft.AspNetCore.Mvc;
using StackExchange.Redis;

namespace BuyGuardian.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ScrapeController : ControllerBase
{
    private readonly IDatabase _redis;
    private readonly ILogger<ScrapeController> _logger;
    private const string QueueName = "olx:urls";

    public ScrapeController(IConnectionMultiplexer redisMuxer, ILogger<ScrapeController> logger)
    {
        _redis = redisMuxer.GetDatabase();
        _logger = logger;
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
}

public class CategoryScrapeRequest
{
    public string Url { get; set; } = string.Empty;
    public int MaxPages { get; set; } = 0; // 0 means infinite
    public int? Page { get; set; }
}
