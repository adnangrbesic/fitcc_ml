using MediatR;
using Microsoft.AspNetCore.Mvc;
using BuyGuardian.Api.Features;

namespace BuyGuardian.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class AnalyzeController : ControllerBase
{
    private readonly IMediator _mediator;

    public AnalyzeController(IMediator mediator)
    {
        _mediator = mediator;
    }

    [HttpPost("{itemId}")]
    public async Task<ActionResult<ListingAnalysisResult>> AnalyzeListing(string itemId)
    {
        try
        {
            var result = await _mediator.Send(new AnalyzeListingQuery(itemId));
            return Ok(result);
        }
        catch (KeyNotFoundException ex)
        {
            return NotFound(ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, $"Internal server error: {ex.Message}");
        }
    }
}
