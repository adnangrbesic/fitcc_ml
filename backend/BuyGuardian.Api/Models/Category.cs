using System.ComponentModel.DataAnnotations;

namespace BuyGuardian.Api.Models;

public class Category
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    public string Name { get; set; } = string.Empty;

    public string LlmPromptTemplate { get; set; } = string.Empty;

    public Dictionary<string, string> ExtractSchema { get; set; } = new();
}
