using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Interfaces;
using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Controllers;

/// <summary>
/// Feedback & voting controller.
/// 
/// #1  — Ground-truth labels for CatBoost retraining (human-in-the-loop)
/// #10 — Upvote/Downvote UI with anti-troll measures
/// 
/// Anti-troll strategy:
///   1. One vote per fingerprint per analysis (SHA-256 hashed, DB unique constraint)
///   2. Bayesian prior: α=10 correct, β=2 incorrect → 83% prior accuracy
///   3. Consistency weighting: users who mostly agree with model get higher vote weight
///   4. Time-gated: vote allowed only after viewing analysis for ≥10 seconds
///   5. Global cooldown: max 1 vote per 3 seconds per fingerprint
///   6. Troll detection: ≥5 downvotes in 1h + >80% downvote ratio → weight=0.1
///   7. Admin bootstrap mode: direct labeling bypasses anti-troll, weight=5.0
/// </summary>
[ApiController]
[Route("api/[controller]")]
public class FeedbackController : ControllerBase
{
    private readonly BuyGuardianContext _context;
    private readonly ILogger<FeedbackController> _logger;

    // Bayesian prior: assume 83% of analyses are correct before any votes
    private const double PriorAlpha = 10.0;  // "correct" votes
    private const double PriorBeta = 2.0;    // "incorrect" votes

    // Time gates
    private static readonly TimeSpan MinViewDuration = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan GlobalCooldown = TimeSpan.FromSeconds(3);

    public FeedbackController(BuyGuardianContext context, ILogger<FeedbackController> logger)
    {
        _context = context;
        _logger = logger;
    }

    /// <summary>
    /// POST /api/feedback/vote
    /// Cast an upvote or downvote on an analysis.
    /// Body: { itemId, vote: "up"|"down", fingerprint, viewedAt }
    /// </summary>
    [HttpPost("vote")]
    public async Task<ActionResult<VoteResponse>> Vote([FromBody] VoteRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.ItemId))
            return BadRequest(new { error = "itemId is required" });

        if (request.Vote != "up" && request.Vote != "down")
            return BadRequest(new { error = "vote must be 'up' or 'down'" });

        if (string.IsNullOrWhiteSpace(request.Fingerprint))
            return BadRequest(new { error = "fingerprint is required" });

        // Hash fingerprint with itemId for privacy (we don't store raw fingerprints)
        var userFp = HashFingerprint(request.Fingerprint, request.ItemId);

        // --- Anti-troll check 1: Time gate ---
        if (request.ViewedAt.HasValue)
        {
            var viewDuration = DateTime.UtcNow - request.ViewedAt.Value;
            if (viewDuration < MinViewDuration)
            {
                return Ok(new VoteResponse
                {
                    Accepted = false,
                    Reason = $"Molimo pregledajte analizu barem {MinViewDuration.TotalSeconds:F0} sekundi prije glasanja.",
                    AggregateScore = null
                });
            }
        }

        // --- Anti-troll check 2: Global cooldown ---
        var lastVote = await _context.AnalysisVotes
            .Where(v => v.UserFingerprint == userFp)
            .OrderByDescending(v => v.CreatedAt)
            .Select(v => v.CreatedAt)
            .FirstOrDefaultAsync();

        if (lastVote != default)
        {
            var timeSinceLastVote = DateTime.UtcNow - lastVote;
            if (timeSinceLastVote < GlobalCooldown)
            {
                return Ok(new VoteResponse
                {
                    Accepted = false,
                    Reason = "Prebrzo glasanje. Sačekajte par sekundi.",
                    AggregateScore = null
                });
            }
        }

        // --- Anti-troll check 3: Duplicate vote ---
        var existingVote = await _context.AnalysisVotes
            .FirstOrDefaultAsync(v => v.ItemId == request.ItemId && v.UserFingerprint == userFp);

        if (existingVote != null)
        {
            return Ok(new VoteResponse
            {
                Accepted = false,
                Reason = "Već ste glasali na ovoj analizi.",
                AggregateScore = await ComputeAggregateScore(request.ItemId)
            });
        }

        // --- Anti-troll check 4: Suspicious pattern ---
        var recentDownvotes = await _context.AnalysisVotes
            .Where(v => v.UserFingerprint == userFp
                     && v.Vote == "down"
                     && v.CreatedAt > DateTime.UtcNow.AddHours(-1))
            .CountAsync();

        var recentTotal = await _context.AnalysisVotes
            .Where(v => v.UserFingerprint == userFp
                     && v.CreatedAt > DateTime.UtcNow.AddHours(-1))
            .CountAsync();

        // If user downvotes >80% of analyses in the last hour with 5+ votes → troll
        double voteWeight = 1.0;
        if (recentTotal >= 5 && (double)recentDownvotes / recentTotal > 0.8)
        {
            voteWeight = 0.1; // Troll weight — barely counts
            _logger.LogWarning(
                "Potential troll detected: fingerprint {Fp}, {Down}/{Total} downvotes in last hour",
                userFp[..8], recentDownvotes, recentTotal);
        }

        // --- Consistency weighting ---
        var listing = await _context.Listings
            .FirstOrDefaultAsync(l => l.ItemId == request.ItemId);

        var vote = new AnalysisVote
        {
            ItemId = request.ItemId,
            Vote = request.Vote,
            UserFingerprint = userFp,
            ModelTrustScore = listing?.TrustScore,
            Weight = voteWeight,
            CreatedAt = DateTime.UtcNow
        };

        _context.AnalysisVotes.Add(vote);
        await _context.SaveChangesAsync();

        // --- Compute aggregate score with Bayesian prior ---
        var aggregate = await ComputeAggregateScore(request.ItemId);

        _logger.LogInformation(
            "Vote recorded: {ItemId} {Vote} by {Fp}, weight={W}, aggregate={Agg:F2}",
            request.ItemId, request.Vote, userFp[..8], voteWeight, aggregate);

        return Ok(new VoteResponse
        {
            Accepted = true,
            Reason = "Hvala na glasanju!",
            AggregateScore = aggregate,
            YourVote = request.Vote
        });
    }

    /// <summary>
    /// GET /api/feedback/vote/{itemId}?fingerprint=xxx
    /// Get the aggregate score and the user's own vote for a listing.
    /// </summary>
    [HttpGet("vote/{itemId}")]
    public async Task<ActionResult<VoteStatusResponse>> GetVoteStatus(
        string itemId, [FromQuery] string fingerprint)
    {
        var userFp = string.IsNullOrWhiteSpace(fingerprint)
            ? null
            : HashFingerprint(fingerprint, itemId);

        var aggregate = await ComputeAggregateScore(itemId);

        string? yourVote = null;
        if (userFp != null)
        {
            yourVote = await _context.AnalysisVotes
                .Where(v => v.ItemId == itemId && v.UserFingerprint == userFp)
                .Select(v => v.Vote)
                .FirstOrDefaultAsync();
        }

        var totalVotes = await _context.AnalysisVotes
            .Where(v => v.ItemId == itemId)
            .CountAsync();

        return Ok(new VoteStatusResponse
        {
            ItemId = itemId,
            AggregateScore = aggregate,
            TotalVotes = totalVotes,
            YourVote = yourVote
        });
    }

    /// <summary>
    /// GET /api/feedback/ground-truth
    /// Returns listings with high-confidence labels for CatBoost training.
    /// In bootstrap mode (minVotes=1), returns ALL labeled listings — useful
    /// when you're the only user labeling data.
    /// </summary>
    [HttpGet("ground-truth")]
    public async Task<ActionResult<List<GroundTruthEntry>>> GetGroundTruth(
        [FromQuery] int minVotes = 1,      // 1 for bootstrap, 3+ for community
        [FromQuery] double minConsensus = 0.51)  // >50% for bootstrap
    {
        var entries = await _context.AnalysisVotes
            .GroupBy(v => v.ItemId)
            .Select(g => new
            {
                ItemId = g.Key,
                Upvotes = g.Count(v => v.Vote == "up"),
                Downvotes = g.Count(v => v.Vote == "down"),
                Total = g.Count(),
                WeightedUp = g.Where(v => v.Vote == "up").Sum(v => v.Weight),
                WeightedDown = g.Where(v => v.Vote == "down").Sum(v => v.Weight),
            })
            .Where(g => g.Total >= minVotes)
            .ToListAsync();

        var results = new List<GroundTruthEntry>();
        foreach (var e in entries)
        {
            double totalWeighted = e.WeightedUp + e.WeightedDown;
            double consensus = totalWeighted > 0
                ? Math.Max(e.WeightedUp, e.WeightedDown) / totalWeighted
                : 0;

            if (consensus >= minConsensus)
            {
                results.Add(new GroundTruthEntry
                {
                    ItemId = e.ItemId,
                    Label = e.WeightedUp > e.WeightedDown ? "trusted" : "suspicious",
                    Confidence = consensus,
                    TotalVotes = e.Total,
                    Upvotes = e.Upvotes,
                    Downvotes = e.Downvotes
                });
            }
        }

        return Ok(results.OrderByDescending(r => r.Confidence).ToList());
    }

    /// <summary>
    /// POST /api/feedback/admin-label
    /// Bootstrap mode: directly assign a ground-truth label to a listing.
    /// For solo developers — creates a weighted vote (x5) that bypasses
    /// anti-troll checks and immediately counts as ground truth.
    /// Body: { itemId, label: "trusted"|"suspicious" }
    /// </summary>
    [HttpPost("admin-label")]
    public async Task<ActionResult<AdminLabelResponse>> AdminLabel([FromBody] AdminLabelRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.ItemId))
            return BadRequest(new { error = "itemId is required" });

        if (request.Label != "trusted" && request.Label != "suspicious")
            return BadRequest(new { error = "label must be 'trusted' or 'suspicious'" });

        var listing = await _context.Listings
            .FirstOrDefaultAsync(l => l.ItemId == request.ItemId);

        // Admin labels use a special fingerprint prefix for tracking
        var adminFp = $"admin:{HashFingerprint("admin-bootstrap", request.ItemId)}";

        // Check if already labeled
        var existing = await _context.AnalysisVotes
            .FirstOrDefaultAsync(v => v.ItemId == request.ItemId && v.UserFingerprint == adminFp);

        if (existing != null)
        {
            existing.Vote = request.Label == "trusted" ? "up" : "down";
            existing.Weight = 5.0; // Admin weight
            existing.CreatedAt = DateTime.UtcNow;
        }
        else
        {
            var vote = new AnalysisVote
            {
                ItemId = request.ItemId,
                Vote = request.Label == "trusted" ? "up" : "down",
                UserFingerprint = adminFp,
                ModelTrustScore = listing?.TrustScore,
                Weight = 5.0, // Admin labels count as 5 regular votes
                CreatedAt = DateTime.UtcNow
            };
            _context.AnalysisVotes.Add(vote);
        }

        await _context.SaveChangesAsync();

        var totalLabeled = await _context.AnalysisVotes
            .Where(v => v.UserFingerprint.StartsWith("admin:"))
            .Select(v => v.ItemId)
            .Distinct()
            .CountAsync();

        return Ok(new AdminLabelResponse
        {
            ItemId = request.ItemId,
            Label = request.Label,
            TotalLabeled = totalLabeled,
            Message = totalLabeled >= 20
                ? $"✅ {totalLabeled} labela spremno! Možeš pokrenuti retrain: POST /api/feedback/retrain-from-labels"
                : $"📝 {totalLabeled}/20 labela. Trebaš još {20 - totalLabeled} za kvalitetan retrain."
        });
    }

    /// <summary>
    /// GET /api/feedback/unlabeled?count=20
    /// Returns listings that need labeling, sorted by priority.
    /// Priority: listings with trust scores near 0.5 (most uncertain) first,
    /// then extreme scores (where model might be wrong).
    /// </summary>
    [HttpGet("unlabeled")]
    public async Task<ActionResult<List<UnlabeledListing>>> GetUnlabeled([FromQuery] int count = 20)
    {
        // Get all itemIds that already have an admin label
        var labeledIds = await _context.AnalysisVotes
            .Where(v => v.UserFingerprint.StartsWith("admin:"))
            .Select(v => v.ItemId)
            .Distinct()
            .ToListAsync();

        // Get listings that have TrustScore but aren't labeled yet
        var candidates = await _context.Listings
            .Where(l => l.IsActive
                     && l.TrustScore != null
                     && !labeledIds.Contains(l.ItemId))
            .OrderBy(l => Math.Abs((l.TrustScore ?? 0.5) - 0.5)) // Closest to 0.5 first = most uncertain
            .ThenBy(l => l.TrustScore) // Then lowest trust first
            .Take(count)
            .Select(l => new UnlabeledListing
            {
                ItemId = l.ItemId,
                Title = l.Title,
                Price = l.Price,
                TrustScore = l.TrustScore ?? 0,
                IsAnomaly = l.IsAnomaly ?? false,
                AnomalyType = l.AnomalyType ?? "",
                Url = $"https://olx.ba/artikal/{l.ItemId.TrimStart('/')}"
            })
            .ToListAsync();

        return Ok(candidates);
    }

    /// <summary>
    /// POST /api/feedback/retrain-from-labels
    /// Triggers CatBoost retraining using admin-labeled ground truth data.
    /// Fetches full listing data from DB and sends it to the ML service.
    /// </summary>
    [HttpPost("retrain-from-labels")]
    public async Task<ActionResult<RetrainResponse>> RetrainFromLabels(
        [FromServices] IMlService mlService)
    {
        // Get all admin-labeled itemIds
        var adminLabels = await _context.AnalysisVotes
            .Where(v => v.UserFingerprint.StartsWith("admin:"))
            .GroupBy(v => v.ItemId)
            .Select(g => new
            {
                ItemId = g.Key,
                Label = g.OrderByDescending(v => v.CreatedAt).First().Vote == "up" ? "trusted" : "suspicious"
            })
            .ToListAsync();

        if (adminLabels.Count < 5)
        {
            return Ok(new RetrainResponse
            {
                Success = false,
                Message = $"Trebaš barem 5 labela za retrain. Trenutno: {adminLabels.Count}.",
                LabelCount = adminLabels.Count
            });
        }

        // Fetch full listing data for each labeled item
        var itemIds = adminLabels.Select(l => l.ItemId).ToList();
        var listings = await _context.Listings
            .Where(l => itemIds.Contains(l.ItemId))
            .Include(l => l.Seller)
            .Include(l => l.Product)
            .ToListAsync();

        var listingMap = listings.ToDictionary(l => l.ItemId, l => l);

        // Send to ML service
        try
        {
            var labelsAsTuples = adminLabels
                .Select(l => (l.ItemId, l.Label))
                .ToList();

            var result = await mlService.TriggerTrustScoreRetrainWithLabelsAsync(
                labelsAsTuples, listingMap);

            return Ok(new RetrainResponse
            {
                Success = result != null,
                Message = result != null
                    ? $"✅ Retrain pokrenut sa {adminLabels.Count} labela ({listings.Count} listinga u bazi)."
                    : "⚠️ ML servis nije odgovorio. Provjeri logove.",
                LabelCount = adminLabels.Count
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Retrain from labels failed");
            return StatusCode(503, new RetrainResponse
            {
                Success = false,
                Message = $"ML servis nedostupan: {ex.Message}",
                LabelCount = adminLabels.Count
            });
        }
    }

    private async Task<double?> ComputeAggregateScore(string itemId)
    {
        var stats = await _context.AnalysisVotes
            .Where(v => v.ItemId == itemId)
            .GroupBy(v => v.ItemId)
            .Select(g => new
            {
                WeightedUp = g.Where(v => v.Vote == "up").Sum(v => v.Weight),
                WeightedDown = g.Where(v => v.Vote == "down").Sum(v => v.Weight),
                Total = g.Count()
            })
            .FirstOrDefaultAsync();

        if (stats == null || stats.Total == 0)
            return null;

        // Only show aggregate when there are multiple votes; otherwise just the user's opinion
        if (stats.Total < 2)
            return null;

        double posteriorAlpha = PriorAlpha + stats.WeightedUp;
        double posteriorBeta = PriorBeta + stats.WeightedDown;
        return posteriorAlpha / (posteriorAlpha + posteriorBeta);
    }

    private static string HashFingerprint(string fingerprint, string itemId)
    {
        var input = $"{fingerprint}:{itemId}:buyguardian-salt";
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}

// ── Request/Response DTOs ──────────────────────────────────────────────────

public class VoteRequest
{
    public string ItemId { get; set; } = string.Empty;
    public string Vote { get; set; } = string.Empty; // "up" or "down"
    public string Fingerprint { get; set; } = string.Empty;
    public DateTime? ViewedAt { get; set; } // When user first saw the analysis
}

public class VoteResponse
{
    public bool Accepted { get; set; }
    public string Reason { get; set; } = string.Empty;
    public double? AggregateScore { get; set; } // Community trust score (0-1)
    public string? YourVote { get; set; }
}

public class VoteStatusResponse
{
    public string ItemId { get; set; } = string.Empty;
    public double? AggregateScore { get; set; }
    public int TotalVotes { get; set; }
    public string? YourVote { get; set; }
}

public class GroundTruthEntry
{
    public string ItemId { get; set; } = string.Empty;
    public string Label { get; set; } = string.Empty; // "trusted" or "suspicious"
    public double Confidence { get; set; }
    public int TotalVotes { get; set; }
    public int Upvotes { get; set; }
    public int Downvotes { get; set; }
}

public class AdminLabelRequest
{
    public string ItemId { get; set; } = string.Empty;
    public string Label { get; set; } = string.Empty; // "trusted" or "suspicious"
}

public class AdminLabelResponse
{
    public string ItemId { get; set; } = string.Empty;
    public string Label { get; set; } = string.Empty;
    public int TotalLabeled { get; set; }
    public string Message { get; set; } = string.Empty;
}

public class UnlabeledListing
{
    public string ItemId { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public decimal Price { get; set; }
    public double TrustScore { get; set; }
    public bool IsAnomaly { get; set; }
    public string AnomalyType { get; set; } = string.Empty;
    public string Url { get; set; } = string.Empty;
}

public class RetrainResponse
{
    public bool Success { get; set; }
    public string Message { get; set; } = string.Empty;
    public int LabelCount { get; set; }
}
