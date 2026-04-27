using System.ComponentModel.DataAnnotations;
using Pgvector;

namespace BuyGuardian.Api.Models;

public class Product
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    public string CanonicalName { get; set; } = string.Empty;

    public string CategoryName { get; set; } = string.Empty;

    public Guid? CategoryId { get; set; }
    public Category? Category { get; set; }

    public Dictionary<string, object> Attributes { get; set; } = new();

    public Vector? ProductVector { get; set; }

    public decimal AvgPrice { get; set; }
    public int ListingsCount { get; set; }

    public ICollection<Listing> Listings { get; set; } = new List<Listing>();
}
