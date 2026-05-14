
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Models;
using BuyGuardian.Api.Extensions;
using BuyGuardian.Api.Interfaces;
using Microsoft.EntityFrameworkCore;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;
using System.Collections.Concurrent;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.AspNetCore.SignalR;

namespace BuyGuardian.Api.Services;

public class ListingConsumer : BackgroundService
{
    private readonly ILogger<ListingConsumer> _logger;
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IConfiguration _configuration;
    private readonly IEmbeddingService _embeddingService;
    private readonly IMlService _mlService;
    private readonly Microsoft.AspNetCore.SignalR.IHubContext<BuyGuardian.Api.Hubs.AnalysisHub> _hubContext;
    
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
        IEmbeddingService embeddingService,
        IMlService mlService,
        Microsoft.AspNetCore.SignalR.IHubContext<BuyGuardian.Api.Hubs.AnalysisHub> hubContext)
    {
        _logger = logger;
        _scopeFactory = scopeFactory;
        _configuration = configuration;
        _embeddingService = embeddingService;
        _mlService = mlService;
        _hubContext = hubContext;
        
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
                _logger.LogDebug("Raw message received: {Json}", json);
                
                var message = JsonSerializer.Deserialize<ListingScrapeMessage>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                
                if (message != null)
                {
                    _logger.LogInformation("Received message from RabbitMQ: ItemId={ItemId}, Title={Title}, HasLlm={HasLlm}", 
                        message.ItemId, message.Title, message.Llm_Metadata != null);
                    messageBuffer.Enqueue((ea.DeliveryTag, message));
                }
                else
                {
                    _logger.LogWarning("Deserialized message is null. Raw JSON: {Json}", json);
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to deserialize message. Moving to DLQ.");
                MoveToDlq(ea.Body.ToArray(), "Deserialization error: " + ex.Message);
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
                if (msg.Price <= 0)
                {
                    _logger.LogWarning("Ignoring listing {ItemId} because price is {Price} (possibly 'po dogovoru').", msg.ItemId, msg.Price);
                    _channel?.BasicAck(tag, false);
                    continue;
                }

                _logger.LogInformation("Processing listing in DB: {ItemId}", msg.ItemId);
                await ProcessSingleListingAsync(db, productMatcher, msg, stoppingToken: default);

                int saved = await db.SaveChangesAsync();
                _logger.LogInformation("Listing {ItemId} saved to DB. Rows affected: {Count}", msg.ItemId, saved);

                // Trigger real-time Isolation Forest and ML trust regression on ingestion
                RunMlScoringInBackgroundAsync(msg.ItemId);

                // Notify UI via SignalR that the scraping and DB insertion is complete
                await _hubContext.Clients.Group(msg.ItemId.ToString()).SendAsync("AnalysisComplete", msg.ItemId);

                _channel?.BasicAck(tag, false);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error processing listing {ItemId}: {Message}", msg.ItemId, ex.Message);
                MoveToDlq(JsonSerializer.SerializeToUtf8Bytes(msg), ex.Message);
                _channel?.BasicAck(tag, false); 
            }
        }
    }

    private async Task ProcessSingleListingAsync(BuyGuardianContext db, IProductMatcher productMatcher, ListingScrapeMessage msg, CancellationToken stoppingToken)
    {
        if (msg.Llm_Metadata == null)
        {
            _logger.LogWarning("Skipping listing {ItemId} because it has no LLM enrichment metadata.", msg.ItemId);
            return;
        }

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
                TrustScore = CalculateSellerTrustScore(msg)
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
            
            // Recalculate dynamic trust score
            seller.TrustScore = CalculateSellerTrustScore(msg);
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
        
        // Robust extraction: Check both top-level and nested 'title' object for canonical info
        string? canonicalName = msg.Llm_Metadata?.Canonical_Name 
                              ?? msg.Llm_Metadata?.Title?.CanonicalName;
        
        double confidence = 0;
        if (msg.Llm_Metadata != null)
        {
            confidence = msg.Llm_Metadata.Canonical_Confidence;
            if (confidence <= 0 && msg.Llm_Metadata.Title != null)
            {
                confidence = msg.Llm_Metadata.Title.CanonicalConfidence;
            }
            
            // Third fallback: If still 0, check Title.Score
            if (confidence <= 0 && msg.Llm_Metadata.Title != null)
            {
                confidence = msg.Llm_Metadata.Title.Score;
            }
        }

        // SANITY GUARD: Clean up LLM hallucinations (brackets) and common shop names/fluff
        if (!string.IsNullOrWhiteSpace(canonicalName))
        {
            // 1. Remove everything inside [brackets] - common LLM formatting artifact
            canonicalName = System.Text.RegularExpressions.Regex.Replace(canonicalName, @"\[.*?\]", "").Trim();
            
            // 2. Dynamic Seller Stripping: If product starts with the seller's name, strip it
            if (!string.IsNullOrEmpty(msg.SellerName) && canonicalName.StartsWith(msg.SellerName, StringComparison.OrdinalIgnoreCase))
            {
                canonicalName = canonicalName.Substring(msg.SellerName.Length).Trim();
            }

            // 3. Remove common shop names, promotional fluff, and redundant technical keywords
            string[] fluff = { 
                "ms brcko", "msbrcko", "mobitel studio", "mixshop", "univerzalno", "fontele", 
                "imtec", "itshop", "olx", "prodajem", "povoljno", "novo", "hitno", 
                "akcija", "zamjena", "mwp", "top", "garancija", "iz brckog", "brcko",
                "ms-brcko", "mobitel-studio", "ram", "storage", "gb ram", "gb storage",
                "interna", "memorija", "u ponudi", "vise komada", "birajte", "vise modela"
            };
            
            string lowerName = canonicalName.ToLowerInvariant();
            foreach (var f in fluff)
            {
                string pattern = $@"\b{System.Text.RegularExpressions.Regex.Escape(f)}\b";
                if (System.Text.RegularExpressions.Regex.IsMatch(lowerName, pattern))
                {
                    canonicalName = System.Text.RegularExpressions.Regex.Replace(canonicalName, pattern, "", System.Text.RegularExpressions.RegexOptions.IgnoreCase).Trim();
                    lowerName = canonicalName.ToLowerInvariant();
                }
            }

            // 4. MULTI-PRODUCT DETECTION: If name contains multiple different GB specs (e.g. 128 and 256), ignore it.
            var gbMatches = System.Text.RegularExpressions.Regex.Matches(lowerName, @"\b(\d+)\s*gb\b")
                .Select(m => m.Groups[1].Value)
                .Distinct()
                .ToList();

            if (gbMatches.Count > 1)
            {
                // If there are multiple GB specs and one is not RAM (usually small), it's a multi-ad
                // To be safe, if we see two "large" numbers (>= 64), it's definitely a multi-ad.
                if (gbMatches.Count(n => int.Parse(n) >= 64) > 1)
                {
                    _logger.LogWarning("Ignoring multi-product listing {ItemId}: {Name}", msg.ItemId, canonicalName);
                    return;
                }
            }

            // 5. Collapse multiple spaces
            canonicalName = System.Text.RegularExpressions.Regex.Replace(canonicalName, @"\s+", " ").Trim();
        }

        // SANITY GUARD: For Mobile Phones, if RAM or Storage exist in extracted attributes, 
        // force append them to canonicalName to guarantee two listings for same phone model/specs always match perfectly.
        if (categoryName == "Mobiteli" && !string.IsNullOrWhiteSpace(canonicalName) && msg.Llm_Metadata?.Attributes != null)
        {
            var attrs = msg.Llm_Metadata.Attributes;
            int ram = ExtractIntAttr(attrs, "ram_gb");
            int storage = ExtractIntAttr(attrs, "storage_gb");
            
            string canonicalLower = canonicalName.ToLowerInvariant();
            
            // Inject RAM spec if not present (using word boundaries to avoid matching 128 in 128gb)
            if (ram > 0 && !System.Text.RegularExpressions.Regex.IsMatch(canonicalLower, $@"\b{ram}\s*gb\b"))
            {
                canonicalName += $" {ram}GB";
            }
            
            // Inject Storage spec if not present
            if (storage > 0 && !System.Text.RegularExpressions.Regex.IsMatch(canonicalLower, $@"\b{storage}\s*gb\b"))
            {
                canonicalName += $" {storage}GB";
            }
            
            _logger.LogInformation("Standardized/Enriched phone canonical name to: {Enriched}", canonicalName);
        }

        // --- CANONICAL NAME SAFETY FILTER (Fail-safe for LLM hallucinations) ---
        if (!string.IsNullOrWhiteSpace(canonicalName))
        {
            // 0. Normalize GB spacing (e.g., "128 GB" -> "128GB") for better deduplication
            canonicalName = System.Text.RegularExpressions.Regex.Replace(canonicalName, @"\b(\d+)\s+gb\b", "$1GB", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            
            // 1. DEDUPLICATE STORAGE & RAM (Fail-safe for LLM hallucinations)
            // We no longer remove RAM, but we ensure things are clean.
            
            // 2. Remove redundant storage mentions (e.g. "2TB ... 2048gb")
            if (canonicalName.Contains("2TB", StringComparison.OrdinalIgnoreCase))
            {
                canonicalName = System.Text.RegularExpressions.Regex.Replace(canonicalName, @"\b2048\s*gb\b", "", System.Text.RegularExpressions.RegexOptions.IgnoreCase).Trim();
            }
            if (canonicalName.Contains("1TB", StringComparison.OrdinalIgnoreCase))
            {
                canonicalName = System.Text.RegularExpressions.Regex.Replace(canonicalName, @"\b1024\s*gb\b", "", System.Text.RegularExpressions.RegexOptions.IgnoreCase).Trim();
            }

            // Remove colors and marketing terms (5G, Dual Sim) that confuse the ML model
            string[] extraFluff = { "black", "blue", "red", "white", "crni", "plavi", "crveni", "bijeli", "silver", "gold", "zlatni", "srebreni", "srebrni", "dual sim", "duos", "5g", "4g" };
            string lowerName = canonicalName.ToLowerInvariant();
            foreach (var f in extraFluff)
            {
                string pattern = $@"\b{System.Text.RegularExpressions.Regex.Escape(f)}\b";
                if (System.Text.RegularExpressions.Regex.IsMatch(lowerName, pattern))
                {
                    canonicalName = System.Text.RegularExpressions.Regex.Replace(canonicalName, pattern, "", System.Text.RegularExpressions.RegexOptions.IgnoreCase).Trim();
                    lowerName = canonicalName.ToLowerInvariant();
                }
            }

            // 3. Deduplicate words (if "256GB 256GB" or "Xiaomi Xiaomi" occurs)
            var words = canonicalName.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            canonicalName = string.Join(" ", words.Distinct(StringComparer.OrdinalIgnoreCase));
            
            // 4. Final trim and space collapse
            canonicalName = System.Text.RegularExpressions.Regex.Replace(canonicalName, @"\s+", " ").Trim();
            
            _logger.LogInformation("Final filtered canonical name: {Filtered}", canonicalName);
        }
            // -----------------------------------------------------------------------

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
                    try
                    {
                        await db.SaveChangesAsync(stoppingToken);
                    }
                    catch (DbUpdateException)
                    {
                        // Race condition: another thread created the product. Fetch it.
                        db.ChangeTracker.Clear(); // Clear failed entry
                        product = await db.Products.FirstOrDefaultAsync(p => p.CanonicalName == canonicalName && p.CategoryId == category.Id, stoppingToken);
                    }
                }
            }

            // d) Listing
            var listing = await db.Listings.FirstOrDefaultAsync(l => l.ItemId == msg.ItemId, stoppingToken);
            bool isNew = false;
            if (listing == null)
            {
                // Robust fix for doubling bug: Always recount from DB instead of incrementing
                category.ListingCount = await db.Listings.CountAsync(l => l.Product != null && l.Product.CategoryId == category.Id, stoppingToken) + 1;
                
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
            // --- UI ALERTS SAFETY GUARD (Fallback & Override) ---
            var alerts = msg.Llm_Metadata.UiAlerts ?? new List<string>();
            
            // 1. Fallback if LLM missed mandatory alerts
            if (!msg.IsNew && !alerts.Contains("Korišten uređaj", StringComparer.OrdinalIgnoreCase)) 
                alerts.Add("Korišten uređaj");
            
            var battery = ExtractIntAttr(msg.Llm_Metadata.Attributes, "battery_health_percent");
            if (battery > 0 && battery < 85 && !alerts.Contains("Loša baterija", StringComparer.OrdinalIgnoreCase)) 
                alerts.Add("Loša baterija");
            if (battery > 0 && battery < 80 && !alerts.Contains("Potreban servis baterije", StringComparer.OrdinalIgnoreCase)) 
                alerts.Add("Potreban servis baterije");
            
            if (msg.Llm_Metadata.Context?.WarrantyMonths == 0 && !alerts.Contains("Bez garancije", StringComparer.OrdinalIgnoreCase) && !alerts.Contains("Nema garancije", StringComparer.OrdinalIgnoreCase)) 
                alerts.Add("Nema garancije");
                
            if (msg.Llm_Metadata.Context?.OverallListingTrust < 6 && !alerts.Contains("Sumnjiv oglas", StringComparer.OrdinalIgnoreCase)) 
                alerts.Add("Sumnjiv oglas");

            // 2. Override Hallucinations: If scraper says NEW, it CANNOT be used
            if (msg.IsNew)
            {
                alerts.RemoveAll(a => a.Equals("Korišten uređaj", StringComparison.OrdinalIgnoreCase));
            }
            
            // 3. Override Hallucinations: If battery is healthy, it cannot be "Bad battery"
            var bh = ExtractIntAttr(msg.Llm_Metadata.Attributes, "battery_health_percent");
            if (bh >= 90)
            {
                alerts.RemoveAll(a => a.Contains("baterija", StringComparison.OrdinalIgnoreCase));
            }

            msg.Llm_Metadata.UiAlerts = alerts.Distinct().ToList();
            // ------------------------------------------------------------

            var cleanedMeta = new Dictionary<string, object>
            {
                ["title"] = msg.Llm_Metadata.Title ?? new LlmTitle(),
                ["category"] = msg.Llm_Metadata.Category,
                ["attributes"] = msg.Llm_Metadata.Attributes,
                ["context"] = msg.Llm_Metadata.Context ?? new LlmContext(),
                ["context_reasoning"] = msg.Llm_Metadata.ContextReasoning ?? new Dictionary<string, object>(),
                ["ui_alerts"] = msg.Llm_Metadata.UiAlerts ?? new List<string>(),
                ["breadcrumbs"] = msg.Breadcrumbs,
                ["raw_specs"] = msg.RawSpecs
            };

            // --- LINGUISTIC PURENESS FILTER (Ekavica to Ijekavica fallback) ---
            if (cleanedMeta.TryGetValue("context_reasoning", out var reasoningObj) && reasoningObj is Dictionary<string, object> reasoningDict)
            {
                var translations = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                {
                    { "vrednost", "vrijednost" }, { "vrednosti", "vrijednosti" },
                    { "deo", "dio" }, { "delova", "dijelova" }, { "delove", "dijelove" }, { "delovi", "dijelovi" },
                    { "mesec", "mjesec" }, { "meseci", "mjeseci" }, { "meseca", "mjeseca" },
                    { "vreme", "vrijeme" }, { "vremena", "vremena" },
                    { "bela", "bijela" }, { "belu", "bijelu" }, { "belog", "bijelog" },
                    { "zamena", "zamjena" }, { "zamene", "zamjene" },
                    { "videti", "vidjeti" }, { "video", "vidio" },
                    { "koristenje", "korištenje" }, { "koristenja", "korištenja" },
                    { "ocena", "ocjena" }, { "ocene", "ocjene" }, { "oceni", "ocjeni" },
                    { "reč", "riječ" }, { "reči", "riječi" }
                };

                foreach (var key in reasoningDict.Keys.ToList())
                {
                    if (reasoningDict[key] is string text)
                    {
                        foreach (var trans in translations)
                        {
                            text = System.Text.RegularExpressions.Regex.Replace(text, $@"\b{trans.Key}\b", trans.Value, System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                        }
                        reasoningDict[key] = text;
                    }
                }
            }
            // ------------------------------------------------------------------

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

        // e) Trigger ML retrain when product group crosses the threshold
        if (product != null && product.ListingsCount >= 5)
        {
            _ = Task.Run(async () =>
            {
                try
                {
                    await _mlService.TriggerRetrainAsync(product.Id);
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "ML retrain trigger failed for product {Id}", product.Id);
                }
            });
        }
    }

    private void RunMlScoringInBackgroundAsync(string itemId)
    {
        _ = Task.Run(async () =>
        {
            try
            {
                using var scope = _scopeFactory.CreateScope();
                var db = scope.ServiceProvider.GetRequiredService<BuyGuardianContext>();
                var mlService = scope.ServiceProvider.GetRequiredService<IMlService>();

                var listing = await db.Listings
                    .Include(l => l.Seller)
                    .FirstOrDefaultAsync(l => l.ItemId == itemId);

                if (listing == null) return;

                _logger.LogInformation("Starting background ML scoring for ItemId {ItemId}", itemId);

                // 1. Anomaly Score (Isolation Forest)
                var anomalyResult = await mlService.GetAnomalyScoreAsync(itemId);
                if (anomalyResult != null)
                {
                    listing.AnomalyScore = anomalyResult.AnomalyScore;
                    listing.IsAnomaly = anomalyResult.IsAnomaly;
                    listing.AnomalyType = anomalyResult.AnomalyType;
                }

                // 1.1 BATCH REFRESH: If product exists, refresh scores for the whole group
                if (listing.ProductId.HasValue)
                {
                    var batchResults = await mlService.GetAnomalyScoreBatchAsync(listing.ProductId.Value);
                    if (batchResults != null && batchResults.Any())
                    {
                        var peerListings = await db.Listings
                            .Where(l => l.ProductId == listing.ProductId && l.ItemId != itemId && l.IsActive)
                            .ToListAsync();

                        foreach (var peer in peerListings)
                        {
                            var score = batchResults.FirstOrDefault(r => r.ItemId == peer.ItemId);
                            if (score != null)
                            {
                                peer.AnomalyScore = score.AnomalyScore;
                                peer.IsAnomaly = score.IsAnomaly;
                                peer.AnomalyType = score.AnomalyType;
                            }
                        }
                        
                        await db.SaveChangesAsync();
                        _logger.LogInformation("Successfully refreshed anomaly scores for {Count} peer listings of product {ProductId}", peerListings.Count, listing.ProductId);
                    }
                }

                // 2. Trust Score (CatBoost Regression Model)
                var trustResult = await mlService.GetTrustScoreAsync(listing, retrain: false);
                if (trustResult != null)
                {
                    listing.TrustScore = Math.Clamp(trustResult.TrustScore / 10.0, 0.0, 1.0);
                }

                await db.SaveChangesAsync();
                _logger.LogInformation("Background ML scoring complete for ItemId {ItemId}. Trust: {Trust:F2}, Anomaly: {IsAnomaly}", 
                    itemId, listing.TrustScore, listing.IsAnomaly);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Background ML scoring failed for ItemId {ItemId}", itemId);
            }
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


    /// <summary>
    /// Dynamic multi-factor seller trust score (0.0–1.0).
    ///   Account Age:        15%  — capped at 36 months
    ///   Feedback Ratio:     40%  — positive / (positive + negative + 1)
    ///   Deliveries:         25%  — log curve, capped at 50
    ///   Verification:       20%  — email 3%, phone 7%, address 10%
    /// </summary>
    private static double CalculateSellerTrustScore(ListingScrapeMessage msg)
    {
        // 1. Account Age (15%) — normalized 0-1 with cap at 36 months
        double ageScore = Math.Min(msg.AccountAgeMonths / 36.0, 1.0);

        // 2. Feedback Ratio (40%) — positive vs negative, smoothed
        int totalFeedback = msg.PositiveFeedback + msg.NeutralFeedback + msg.NegativeFeedback;
        double feedbackScore;
        if (totalFeedback == 0)
        {
            feedbackScore = 0.5; // Neutral baseline for new sellers
        }
        else
        {
            feedbackScore = (double)msg.PositiveFeedback / (msg.PositiveFeedback + msg.NegativeFeedback + 1);
        }

        // 3. Successful Deliveries (25%) — log curve capped at 50
        double deliveryScore = Math.Min(Math.Log(1 + msg.SuccessfulDeliveries) / Math.Log(51), 1.0);

        // 4. Verification (20%) — email 3%, phone 7%, address 10%
        double verificationScore = 0.0;
        if (msg.IsEmailVerified)   verificationScore += 0.15;
        if (msg.IsPhoneVerified)   verificationScore += 0.35;
        if (msg.IsAddressVerified) verificationScore += 0.50;

        double trust = (ageScore * 0.15)
                     + (feedbackScore * 0.40)
                     + (deliveryScore * 0.25)
                     + (verificationScore * 0.20);

        return Math.Clamp(trust, 0.0, 1.0);
    }

    private int ExtractIntAttr(Dictionary<string, object> attrs, string key)
    {
        if (attrs.TryGetValue(key, out var val))
        {
            if (val is int i) return i;
            if (val is long l) return (int)l;
            if (val is double d) return (int)d;
            if (val is System.Text.Json.JsonElement je && je.ValueKind == System.Text.Json.JsonValueKind.Number) 
                return je.GetInt32();
            
            if (val is string s)
            {
                // Remove non-numeric fluff if any
                var match = System.Text.RegularExpressions.Regex.Match(s, @"\d+");
                if (match.Success && int.TryParse(match.Value, out var parsed)) return parsed;
            }
        }
        return 0;
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
    
    [JsonPropertyName("overall_trust")] // Fallback for overall_listing_trust
    public double? OverallTrustFallback { get; set; }

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
    
    [JsonPropertyName("ui_alerts")]
    public List<string>? UiAlerts { get; set; } = new();
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
