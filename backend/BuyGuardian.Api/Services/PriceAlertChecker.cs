using System.Collections.Concurrent;
using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Data;

namespace BuyGuardian.Api.Services;

/// <summary>
/// Background service that checks price alerts every 2 hours.
/// When a listing's price drops below the subscribed target, 
/// the alert is queued for the Chrome extension to poll via notifications API.
/// </summary>
public class PriceAlertChecker : BackgroundService
{
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<PriceAlertChecker> _logger;
    private readonly TimeSpan _checkInterval = TimeSpan.FromHours(2);

    // In-memory set of recently triggered alerts for fast polling
    // Maps userFingerprint → list of triggered itemIds
    private static readonly ConcurrentDictionary<string, List<TriggeredAlertInfo>> TriggeredAlerts = new();

    public PriceAlertChecker(IServiceScopeFactory scopeFactory, ILogger<PriceAlertChecker> logger)
    {
        _scopeFactory = scopeFactory;
        _logger = logger;
    }

    /// <summary>
    /// GET /api/listings/alerts/pending?fingerprint=xxx
    /// Extension polls this to get triggered alerts for push notification.
    /// </summary>
    public static List<TriggeredAlertInfo> DrainTriggeredAlerts(string userFingerprint)
    {
        if (TriggeredAlerts.TryRemove(userFingerprint, out var alerts))
            return alerts;
        return new List<TriggeredAlertInfo>();
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        // Initial delay to let the app start
        await Task.Delay(TimeSpan.FromMinutes(1), stoppingToken);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await CheckAlerts(stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error checking price alerts");
            }

            await Task.Delay(_checkInterval, stoppingToken);
        }
    }

    private async Task CheckAlerts(CancellationToken ct)
    {
        using var scope = _scopeFactory.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<BuyGuardianContext>();

        var activeAlerts = await context.PriceAlerts
            .Where(a => a.IsActive && !a.Triggered)
            .ToListAsync(ct);

        if (!activeAlerts.Any()) return;

        var itemIds = activeAlerts.Select(a => a.ItemId).Distinct().ToList();
        var listings = await context.Listings
            .Where(l => itemIds.Contains(l.ItemId))
            .ToDictionaryAsync(l => l.ItemId, l => l, ct);

        var triggeredCount = 0;
        foreach (var alert in activeAlerts)
        {
            if (!listings.TryGetValue(alert.ItemId, out var listing))
                continue;

            var currentPrice = listing.Price;
            var priceDropped = alert.TargetPrice.HasValue
                ? currentPrice <= alert.TargetPrice.Value
                : currentPrice < alert.SubscribedPrice;

            if (priceDropped && currentPrice > 0)
            {
                alert.Triggered = true;
                alert.TriggeredAt = DateTime.UtcNow;
                alert.IsActive = false; // One-shot alert

                // Queue for extension polling
                var info = new TriggeredAlertInfo
                {
                    ItemId = alert.ItemId,
                    Title = listing.Title,
                    OldPrice = alert.SubscribedPrice,
                    NewPrice = currentPrice,
                    Savings = alert.SubscribedPrice - currentPrice,
                    SavingsPercent = alert.SubscribedPrice > 0
                        ? Math.Round((double)((alert.SubscribedPrice - currentPrice) / alert.SubscribedPrice) * 100, 1)
                        : 0
                };

                TriggeredAlerts.AddOrUpdate(
                    alert.UserFingerprint,
                    _ => new List<TriggeredAlertInfo> { info },
                    (_, list) => { list.Add(info); return list; });

                triggeredCount++;
            }

            alert.LastCheckedAt = DateTime.UtcNow;
        }

        if (triggeredCount > 0)
        {
            await context.SaveChangesAsync(ct);
            _logger.LogInformation("Triggered {Count} price alerts", triggeredCount);
        }
    }
}

public class TriggeredAlertInfo
{
    public string ItemId { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public decimal OldPrice { get; set; }
    public decimal NewPrice { get; set; }
    public decimal Savings { get; set; }
    public double SavingsPercent { get; set; }
}
