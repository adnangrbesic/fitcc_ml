using System.ComponentModel.DataAnnotations;

namespace BuyGuardian.Api.Models;

public class Seller
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    public string OlxId { get; set; } = string.Empty;

    [Required]
    public string Username { get; set; } = string.Empty;

    public int AccountAgeMonths { get; set; }
    
    public int PositiveFeedback { get; set; }
    
    public double TrustScore { get; set; }

    public ICollection<Listing> Listings { get; set; } = new List<Listing>();
}
