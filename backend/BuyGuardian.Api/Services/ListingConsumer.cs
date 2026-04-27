
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Models;
using BuyGuardian.Api.Extensions;
using Microsoft.EntityFrameworkCore;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;
using System.Collections.Concurrent;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.DependencyInjection;

namespace BuyGuardian.Api.Services;

public class ListingConsumer : BackgroundService
{
    private readonly ILogger<ListingConsumer> _logger;
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IConfiguration _configuration;
    private readonly IEmbeddingService _embeddingService;
    
    private IConnection? _connection;

    private IModel? _channel;
    
    private const string QueueName = "listing_scrape";
    private const string DlqName = "dlq_scrape";
    private const int BatchSize = 100;
    private const int MaxRetries = 3;

    public ListingConsumer(
        ILogger<ListingConsumer> logger, 
        IServiceScopeFactory scopeFactory, 
        IConfiguration configuration,
        IEmbeddingService embeddingService)
    {
        _logger = logger;
        _scopeFactory = scopeFactory;
        _configuration = configuration;
        _embeddingService = embeddingService;
        InitializeRabbitMQ();
    }


    private void InitializeRabbitMQ()
    {
        var factory = new ConnectionFactory { HostName = _configuration["RabbitMQ:HostName"] ?? "localhost" };
        
        int attempts = 0;
        while (attempts < 10)
        {
            try
            {
                _connection = factory.CreateConnection();
                _channel = _connection.CreateModel();

                // Main Queue
                _channel.QueueDeclare(QueueName, durable: true, exclusive: false, autoDelete: false);
                
                // DLQ
                _channel.QueueDeclare(DlqName, durable: true, exclusive: false, autoDelete: false);

                _logger.LogInformation("RabbitMQ connected to queue: {QueueName}", QueueName);
                return;
            }
            catch (Exception ex)
            {
                attempts++;
                _logger.LogWarning(ex, "RabbitMQ connection attempt {Attempts} failed. Retrying in 5s...", attempts);
                Thread.Sleep(5000);
            }
        }
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (_channel == null) return;

        var consumer = new EventingBasicConsumer(_channel);
        var messageBuffer = new ConcurrentQueue<(ulong DeliveryTag, ListingScrapeMessage Message)>();

        consumer.Received += (model, ea) =>
        {
            try
            {
                var body = ea.Body.ToArray();
                var json = Encoding.UTF8.GetString(body);
                var message = JsonSerializer.Deserialize<ListingScrapeMessage>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                
                if (message != null)
                {
                    _logger.LogInformation("Received message from RabbitMQ: {ItemId}", message.ItemId);
                    messageBuffer.Enqueue((ea.DeliveryTag, message));
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to deserialize message. Moving to DLQ.");
                MoveToDlq(ea.Body.ToArray(), "Deserialization error");
                _channel.BasicAck(ea.DeliveryTag, false);
            }
        };

        _channel.BasicConsume(QueueName, autoAck: false, consumer: consumer);

        var lastProcessTime = DateTime.UtcNow;

        while (!stoppingToken.IsCancellationRequested)
        {
            bool shouldProcess = false;
            if (messageBuffer.Count >= BatchSize)
            {
                shouldProcess = true;
            }
            else if (messageBuffer.Count > 0 && (DateTime.UtcNow - lastProcessTime).TotalSeconds >= 5)
            {
                _logger.LogInformation("Processing partial batch after timeout ({Count} messages)", messageBuffer.Count);
                shouldProcess = true;
            }

            if (shouldProcess)
            {
                await ProcessBatchAsync(messageBuffer);
                lastProcessTime = DateTime.UtcNow;
            }
            
            await Task.Delay(1000, stoppingToken);
        }
    }

    private async Task ProcessBatchAsync(ConcurrentQueue<(ulong DeliveryTag, ListingScrapeMessage Message)> buffer)
    {
        var batch = new List<(ulong DeliveryTag, ListingScrapeMessage Message)>();
        while (batch.Count < BatchSize && buffer.TryDequeue(out var item))
        {
            batch.Add(item);
        }

        if (batch.Count == 0) return;

        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<BuyGuardianContext>();
        var productMatcher = scope.ServiceProvider.GetRequiredService<IProductMatcher>();

        _logger.LogInformation("Processing batch of {Count} listings", batch.Count);

        foreach (var (tag, msg) in batch)
        {
            try
            {
                _logger.LogInformation("Processing listing: {ItemId} - {Title}", msg.ItemId, msg.Title);
                await ProcessSingleListingAsync(db, productMatcher, msg, stoppingToken: default);

                
                int saved = await db.SaveChangesAsync();
                _logger.LogInformation("Listing {ItemId} saved to DB. Rows affected: {Count}", msg.ItemId, saved);

                _channel?.BasicAck(tag, false);
                _logger.LogInformation("Successfully processed and Acked listing: {ItemId}", msg.ItemId);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error processing listing {ItemId}. Retrying/DLQ...", msg.ItemId);
                MoveToDlq(JsonSerializer.SerializeToUtf8Bytes(msg), ex.Message);
                _channel?.BasicAck(tag, false); 
            }
        }
    }

    private async Task ProcessSingleListingAsync(BuyGuardianContext db, IProductMatcher productMatcher, ListingScrapeMessage msg, CancellationToken stoppingToken)

    {
        // a) Seller
        var seller = await db.Sellers.FirstOrDefaultAsync(s => s.OlxId == msg.Seller_OlxId, stoppingToken);
        if (seller == null)
        {
            seller = new Seller
            {
                OlxId = msg.Seller_OlxId,
                Username = string.IsNullOrEmpty(msg.SellerName) ? msg.Seller_OlxId : msg.SellerName,
                PositiveFeedback = msg.PositiveFeedback,
                NeutralFeedback = msg.NeutralFeedback,
                NegativeFeedback = msg.NegativeFeedback,
                SuccessfulDeliveries = msg.SuccessfulDeliveries,
                IsEmailVerified = msg.IsEmailVerified,
                IsPhoneVerified = msg.IsPhoneVerified,
                IsAddressVerified = msg.IsAddressVerified,
                AccountAgeMonths = msg.AccountAgeMonths,
                TrustScore = msg.PositiveFeedback > 0 ? Math.Min(100, 50 + (msg.PositiveFeedback / 10.0)) : 50.0 // Dynamic initial score
            };
            db.Sellers.Add(seller);
        }
        else 
        {
            // Update existing seller data
            seller.Username = string.IsNullOrEmpty(msg.SellerName) ? seller.Username : msg.SellerName;
            seller.PositiveFeedback = msg.PositiveFeedback;
            seller.NeutralFeedback = msg.NeutralFeedback;
            seller.NegativeFeedback = msg.NegativeFeedback;
            seller.SuccessfulDeliveries = msg.SuccessfulDeliveries;
            seller.IsEmailVerified = msg.IsEmailVerified;
            seller.IsPhoneVerified = msg.IsPhoneVerified;
            seller.IsAddressVerified = msg.IsAddressVerified;
            seller.AccountAgeMonths = msg.AccountAgeMonths;
            
            // Recalculate trust if needed
            seller.TrustScore = msg.PositiveFeedback > 0 ? Math.Min(100, 50 + (msg.PositiveFeedback / 10.0)) : seller.TrustScore;
        }
        await db.SaveChangesAsync(stoppingToken); // Commit to get ID for FK

        // b) Category - Take the LAST breadcrumb for specificity
        string categoryName = msg.Llm_Metadata?.Category ?? "General";
        if (!string.IsNullOrEmpty(msg.Breadcrumbs))
        {
            var parts = msg.Breadcrumbs.Split('>', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            if (parts.Length > 0)
            {
                categoryName = parts.Last();
                
                // Normalization
                if (categoryName == "Mobilni uređaji") categoryName = "Mobiteli";
                if (categoryName == "Kamera i fotoaparati") categoryName = "Fotoaparati";
                
                _logger.LogInformation("Normalized category from breadcrumbs: {CategoryName}", categoryName);
            }
        }

        var category = await db.Categories.FirstOrDefaultAsync(c => c.Name == categoryName, stoppingToken);
        if (category == null)
        {
            category = new Category { Name = categoryName };
            db.Categories.Add(category);
            await db.SaveChangesAsync(stoppingToken);
        }

        // c) Product (Smart Deduplication)
        Product? product = null;
        string? canonicalName = msg.Llm_Metadata?.Canonical_Name ?? msg.Llm_Metadata?.Title?.CanonicalName;
        double confidence = msg.Llm_Metadata?.Canonical_Confidence ?? msg.Llm_Metadata?.Title?.CanonicalConfidence ?? 0;

        if (!string.IsNullOrWhiteSpace(canonicalName))
        {
            var matchedId = await productMatcher.MatchProductAsync(db, canonicalName, confidence);
            if (matchedId.HasValue)

            {
                product = await db.Products.FindAsync(matchedId.Value);
                if (product != null)
                {
                    product.CategoryId = category.Id;
                    product.CategoryName = category.Name;
                }
            }

            if (product == null)
            {
                var attrs = msg.Llm_Metadata?.Attributes ?? new Dictionary<string, object>();
                var transientKeys = new[] { "mileage", "mileage_km", "condition", "stanje", "km", "kilometri" };
                foreach (var key in transientKeys) attrs.Remove(key);

                _logger.LogInformation("Creating new product for canonical name: {Canonical}", canonicalName);
                var vector = await _embeddingService.GetEmbeddingAsync(canonicalName);

                product = new Product
                {
                    CanonicalName = canonicalName,
                    CategoryId = category.Id,
                    CategoryName = category.Name,
                    Attributes = attrs,
                    ProductVector = vector
                };
                db.Products.Add(product);
                await db.SaveChangesAsync(stoppingToken);
            }
        }

        // d) Listing
        var listing = await db.Listings.FirstOrDefaultAsync(l => l.ItemId == msg.ItemId, stoppingToken);
        bool isNew = false;
        if (listing == null)
        {
            category.ListingCount++;
            listing = new Listing
            {
                ItemId = msg.ItemId,
                SellerId = seller.Id,
                ProductId = product?.Id,
                Title = msg.Title,
                Description = msg.Description,
                Price = (decimal)msg.Price,
                IsActive = msg.IsActive,
                IsNew = msg.IsNew,
                ScrapedAt = msg.ScrapedAt.HasValue 
                    ? DateTime.SpecifyKind(msg.ScrapedAt.Value, DateTimeKind.Utc) 
                    : DateTime.UtcNow
            };
            db.Listings.Add(listing);
            isNew = true;
        }
        else
        {
            _logger.LogInformation("Processing listing: {ItemId} - {Title}. TrustScore from LLM: {Score}", 
            msg.ItemId, msg.Title, msg.Llm_Metadata?.Context?.OverallListingTrust);

            listing.SellerId = seller.Id;
            listing.ProductId = product?.Id;
            listing.Title = msg.Title;
            listing.Description = msg.Description;
            listing.Price = (decimal)msg.Price;
            listing.TrustScore = msg.Llm_Metadata?.Context?.OverallListingTrust;
            listing.IsActive = msg.IsActive;
            listing.IsNew = msg.IsNew;
            listing.ScrapedAt = msg.ScrapedAt.HasValue 
                ? DateTime.SpecifyKind(msg.ScrapedAt.Value, DateTimeKind.Utc) 
                : DateTime.UtcNow;
        }
        
        // Clean metadata: Strip reasoning to save space
        if (msg.Llm_Metadata != null)
        {
            var cleanedMeta = new Dictionary<string, object>
            {
                ["title"] = msg.Llm_Metadata.Title ?? new LlmTitle(),
                ["category"] = msg.Llm_Metadata.Category,
                ["attributes"] = msg.Llm_Metadata.Attributes,
                ["context"] = msg.Llm_Metadata.Context ?? new LlmContext(),
                ["context_reasoning"] = msg.Llm_Metadata.ContextReasoning ?? new Dictionary<string, object>(),
                ["breadcrumbs"] = msg.Breadcrumbs,
                ["raw_specs"] = msg.RawSpecs
            };
            listing.RawMetadata = cleanedMeta;
        }
        else 
        {
            listing.RawMetadata = new Dictionary<string, object> { ["breadcrumbs"] = msg.Breadcrumbs };
        }

        if (isNew) await db.SaveChangesAsync(stoppingToken); // Ensure ID for PriceHistory

        // Update Product Stats if linked
        if (product != null)
        {
            var allPrices = await db.Listings
                .Where(l => l.ProductId == product.Id && l.IsActive)
                .Select(l => l.Price)
                .ToListAsync(stoppingToken);
            
            product.ListingsCount = allPrices.Count;
            if (allPrices.Any())
            {
                product.AvgPrice = allPrices.Average();
            }
        }

        // d) PriceHistory
        db.PriceHistories.Add(new PriceHistory
        {
            ListingId = listing.Id,
            Price = listing.Price,
            RecordedAt = DateTime.UtcNow
        });
    }

    private bool AttributesMatch(Dictionary<string, object> existing, Dictionary<string, object> incoming)
    {
        // Simple comparison: check if key specs match (ram, storage, year, etc.)
        // We only check keys that exist in both.
        var criticalKeys = new[] { "ram_gb", "storage_gb", "year", "engine_capacity", "mileage", "fuel_type" };
        
        foreach (var key in criticalKeys)
        {
            if (existing.TryGetValue(key, out var eVal) && incoming.TryGetValue(key, out var iVal))
            {
                if (eVal?.ToString() != iVal?.ToString()) return false;
            }
        }
        return true;
    }

    private void MoveToDlq(byte[] body, string reason)
    {
        var properties = _channel?.CreateBasicProperties();
        properties!.Headers = new Dictionary<string, object> { { "x-dead-letter-reason", reason } };
        _channel?.BasicPublish("", DlqName, properties, body);
    }

    public override void Dispose()
    {
        _channel?.Close();
        _connection?.Close();
        base.Dispose();
    }
}

public class ListingScrapeMessage
{
    [JsonPropertyName("item_id")]
    public string ItemId { get; set; } = string.Empty;
    
    [JsonPropertyName("title")]
    public string Title { get; set; } = string.Empty;
    
    [JsonPropertyName("description")]
    public string Description { get; set; } = string.Empty;
    
    [JsonPropertyName("price")]
    public double Price { get; set; }

    [JsonPropertyName("currency")]
    public string Currency { get; set; } = "KM";
    
    [JsonPropertyName("seller_id")]
    public string Seller_OlxId { get; set; } = string.Empty;

    [JsonPropertyName("seller_name")]
    public string SellerName { get; set; } = string.Empty;

    [JsonPropertyName("is_email_verified")]
    public bool IsEmailVerified { get; set; }

    [JsonPropertyName("is_phone_verified")]
    public bool IsPhoneVerified { get; set; }

    [JsonPropertyName("is_address_verified")]
    public bool IsAddressVerified { get; set; }

    [JsonPropertyName("positive_feedback")]
    public int PositiveFeedback { get; set; }

    [JsonPropertyName("neutral_feedback")]
    public int NeutralFeedback { get; set; }

    [JsonPropertyName("negative_feedback")]
    public int NegativeFeedback { get; set; }

    [JsonPropertyName("successful_deliveries")]
    public int SuccessfulDeliveries { get; set; }

    [JsonPropertyName("account_age")]
    public string AccountAge { get; set; } = string.Empty;

    [JsonPropertyName("account_age_months")]
    public int AccountAgeMonths { get; set; }

    [JsonPropertyName("location")]
    public string Location { get; set; } = string.Empty;

    [JsonPropertyName("phone_number")]
    public string PhoneNumber { get; set; } = string.Empty;

    [JsonPropertyName("is_promoted")]
    public bool IsPromoted { get; set; }

    [JsonPropertyName("is_active")]
    public bool IsActive { get; set; }

    [JsonPropertyName("is_new")]
    public bool IsNew { get; set; }

    [JsonPropertyName("breadcrumbs")]
    public string Breadcrumbs { get; set; } = string.Empty;

    [JsonPropertyName("raw_specs")]
    public Dictionary<string, string> RawSpecs { get; set; } = new();
    
    [JsonPropertyName("llm_enrichment")]
    public LlmMetadata? Llm_Metadata { get; set; }
    
    [JsonPropertyName("scraped_at")]
    public DateTime? ScrapedAt { get; set; }
}

public class LlmMetadata
{
    [JsonPropertyName("canonical_name")]
    public string? Canonical_Name { get; set; }

    [JsonPropertyName("canonical_confidence")]
    public double Canonical_Confidence { get; set; }

    [JsonPropertyName("title")]
    public LlmTitle? Title { get; set; }

    [JsonPropertyName("category")]
    public string Category { get; set; } = "General";

    [JsonPropertyName("attributes")]
    public Dictionary<string, object> Attributes { get; set; } = new();

    [JsonPropertyName("context")]
    public LlmContext? Context { get; set; }

    [JsonPropertyName("context_reasoning")]
    public Dictionary<string, object>? ContextReasoning { get; set; }
}

public class LlmTitle
{
    [JsonPropertyName("short")]
    public string Short { get; set; } = string.Empty;

    [JsonPropertyName("long")]
    public string Long { get; set; } = string.Empty;

    [JsonPropertyName("score")]
    public double Score { get; set; }

    [JsonPropertyName("canonical_name")]
    public string? CanonicalName { get; set; }

    [JsonPropertyName("canonical_confidence")]
    public double CanonicalConfidence { get; set; }
}

public class LlmContext
{
    [JsonPropertyName("condition")]
    public double Condition { get; set; }

    [JsonPropertyName("overpay_ratio")]
    public double OverpayRatio { get; set; }

    [JsonPropertyName("warranty_months")]
    public int WarrantyMonths { get; set; }

    [JsonPropertyName("special_warranty")]
    public string? SpecialWarranty { get; set; }

    [JsonPropertyName("writing_quality")]
    public double WritingQuality { get; set; }

    [JsonPropertyName("overall_listing_trust")]
    public double OverallListingTrust { get; set; }
}
