using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuyGuardian.Api.Models;

public class SearchQuery
{
    [Key]
    [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
    public int Id { get; set; }

    [Required]
    public string QueryTerm { get; set; } = string.Empty;

    public string Category { get; set; } = string.Empty;

    public DateTime? LastScrape { get; set; }

    public DateTime NextScrape { get; set; } = DateTime.UtcNow;

    public double PriorityScore { get; set; }

    public int ListingsCount { get; set; }

    [Column(TypeName = "decimal(18,2)")]
    public decimal AvgPrice { get; set; }

    public double VelocityScore { get; set; }
}
