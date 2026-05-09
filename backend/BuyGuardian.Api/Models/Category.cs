using System.ComponentModel.DataAnnotations;

namespace BuyGuardian.Api.Models;

public class Category
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    public string Name { get; set; } = string.Empty;

    public string LlmPromptTemplate { get; set; } = string.Empty;

    public string? ExtractSchema { get; set; }
    public int ListingCount { get; set; }

    /// <summary>
    /// Isolation Forest contamination parameter override for this category.
    /// Default 0.10 (10%). Lower = fewer anomalies flagged.
    /// </summary>
    public double IFContamination { get; set; } = 0.10;
}
