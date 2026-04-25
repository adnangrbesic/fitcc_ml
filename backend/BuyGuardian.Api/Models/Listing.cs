using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuyGuardian.Api.Models;

public class Listing
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    public string ItemId { get; set; } = string.Empty;

    public Guid SellerId { get; set; }
    public Seller? Seller { get; set; }

    public Guid? ProductId { get; set; }
    public Product? Product { get; set; }

    [Required]
    public string Title { get; set; } = string.Empty;

    public string Description { get; set; } = string.Empty;

    [Column(TypeName = "decimal(18,2)")]
    public decimal Price { get; set; }

    public Dictionary<string, object> RawMetadata { get; set; } = new();

    public double? TrustScore { get; set; }

    public bool IsActive { get; set; } = true;

    public DateTime ScrapedAt { get; set; } = DateTime.UtcNow;

    public ICollection<PriceHistory> PriceHistories { get; set; } = new List<PriceHistory>();
}
