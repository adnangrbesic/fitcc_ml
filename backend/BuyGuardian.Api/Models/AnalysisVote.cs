using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuyGuardian.Api.Models;

/// <summary>
/// Stores user feedback/votes on analysis results.
/// Used both for the upvote/downvote UI (#10) and as ground-truth
/// labels for CatBoost retraining (#1).
/// 
/// Anti-troll measures:
///   - One vote per fingerprint per analysis (unique index)
///   - Bayesian prior: model starts with "trusted" prior, trolls need many votes to shift it
///   - Fingerprint consistency tracked for weighting
/// </summary>
public class AnalysisVote
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    /// <summary>The listing/item being voted on.</summary>
    [Required]
    [MaxLength(128)]
    public string ItemId { get; set; } = string.Empty;

    /// <summary>"up" or "down"</summary>
    [Required]
    [MaxLength(4)]
    public string Vote { get; set; } = string.Empty; // "up" or "down"

    /// <summary>
    /// Hashed user fingerprint (SHA-256 of browser fingerprint + itemId).
    /// This is our "anonymous but unique" user identifier.
    /// </summary>
    [Required]
    [MaxLength(64)]
    public string UserFingerprint { get; set; } = string.Empty;

    /// <summary>
    /// The trust score the model predicted at the time of voting.
    /// Used to measure voter consistency (does this user agree with the model?).
    /// </summary>
    public double? ModelTrustScore { get; set; }

    /// <summary>When the vote was cast.</summary>
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    /// <summary>
    /// Weight of this vote in the aggregate score.
    /// Starts at 1.0, adjusted by anti-troll heuristics.
    /// </summary>
    public double Weight { get; set; } = 1.0;

    // Navigation
    public Listing? Listing { get; set; }
}
