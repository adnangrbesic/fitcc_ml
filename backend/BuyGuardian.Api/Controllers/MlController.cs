using Microsoft.AspNetCore.Mvc;
using BuyGuardian.Api.Interfaces;

namespace BuyGuardian.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class MlController : ControllerBase
{
    private readonly IMlService _mlService;
    private readonly ILogger<MlController> _logger;

    public MlController(IMlService mlService, ILogger<MlController> logger)
    {
        _mlService = mlService;
        _logger = logger;
    }

    [HttpPost("trust-score/retrain-full")]
    public async Task<IActionResult> RetrainTrustScoreModel()
    {
        var result = await _mlService.TriggerTrustScoreFullRetrainAsync();
        if (result == null)
        {
            _logger.LogWarning("Trust score retrain request failed");
            return StatusCode(503, "Trust score service unavailable or returned an error.");
        }

        return Ok(result);
    }
}
