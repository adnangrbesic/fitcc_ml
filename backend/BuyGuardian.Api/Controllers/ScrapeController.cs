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
        await _redis.ListLeftPushAsync(QueueName, url);
        return Ok(new { Message = "URL added to queue", Queue = QueueName, Url = url });
    }

    [HttpPost("queue-batch")]
    public async Task<IActionResult> QueueBatch([FromBody] string[] urls)
    {
        if (urls == null || urls.Length == 0) return BadRequest("URLs are required");

        foreach (var url in urls)
        {
            await _redis.ListLeftPushAsync(QueueName, url);
        }
        
        return Ok(new { Message = $"{urls.Length} URLs added to queue" });
    }
}
