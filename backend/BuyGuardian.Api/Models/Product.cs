using System.ComponentModel.DataAnnotations;
using Pgvector;

namespace BuyGuardian.Api.Models;

public class Product
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    public string CanonicalName { get; set; } = string.Empty;

    [Required]
    public string Category { get; set; } = string.Empty;

    public Dictionary<string, object> Attributes { get; set; } = new();

    public Vector? ProductVector { get; set; }

    public ICollection<Listing> Listings { get; set; } = new List<Listing>();
}
