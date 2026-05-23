using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuyGuardian.Api.Models;

/// <summary>
/// Price alert subscription — user wants to be notified when a listing's price drops.
/// </summary>
public class PriceAlert
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    /// <summary>The listing being tracked.</summary>
    [Required]
    [MaxLength(128)]
    public string ItemId { get; set; } = string.Empty;

    /// <summary>Hashed user fingerprint for anonymous identification.</summary>
    [Required]
    [MaxLength(64)]
    public string UserFingerprint { get; set; } = string.Empty;

    /// <summary>Price at the time of subscription (baseline).</summary>
    [Column(TypeName = "decimal(18,2)")]
    public decimal SubscribedPrice { get; set; }

    /// <summary>
    /// Target price threshold. Alert triggers when price drops below this.
    /// If null, alerts on ANY price drop.
    /// </summary>
    [Column(TypeName = "decimal(18,2)")]
    public decimal? TargetPrice { get; set; }

    /// <summary>Whether the alert is still active.</summary>
    public bool IsActive { get; set; } = true;

    /// <summary>Whether the alert has been triggered (and notification sent).</summary>
    public bool Triggered { get; set; } = false;

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    /// <summary>When the alert was last checked.</summary>
    public DateTime? LastCheckedAt { get; set; }

    /// <summary>When the alert was triggered (notification sent).</summary>
    public DateTime? TriggeredAt { get; set; }

    // Navigation
    public Listing? Listing { get; set; }
}
