using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class CategoriesController : ControllerBase
{
    private readonly BuyGuardianContext _context;

    public CategoriesController(BuyGuardianContext context)
    {
        _context = context;
    }

    [HttpGet]
    public async Task<ActionResult<IEnumerable<Category>>> GetCategories()
    {
        return await _context.Categories.ToListAsync();
    }

    [HttpGet("{name}")]
    public async Task<ActionResult<Category>> GetCategory(string name)
    {
        var category = await _context.Categories.FirstOrDefaultAsync(c => c.Name == name);

        if (category == null)
        {
            return NotFound();
        }

        return category;
    }

    [HttpPut("{name}/prompt")]
    public async Task<IActionResult> UpdatePrompt(string name, [FromBody] string prompt)
    {
        var category = await _context.Categories.FirstOrDefaultAsync(c => c.Name == name);

        if (category == null)
        {
            // If doesn't exist, create it
            category = new Category { Name = name, LlmPromptTemplate = prompt };
            _context.Categories.Add(category);
        }
        else
        {
            category.LlmPromptTemplate = prompt;
        }

        await _context.SaveChangesAsync();

        return NoContent();
    }
}
