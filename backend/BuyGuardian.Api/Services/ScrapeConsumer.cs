using RabbitMQ.Client;
using RabbitMQ.Client.Events;
using Microsoft.EntityFrameworkCore;
using System.Text;
using System.Text.Json;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Services;

public class ScrapeConsumer : BackgroundService
{
    private readonly ILogger<ScrapeConsumer> _logger;
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IConfiguration _configuration;
    private IConnection? _connection;
    private IModel? _channel;
    private const string QueueName = "listing_scrape";

    public ScrapeConsumer(ILogger<ScrapeConsumer> logger, IServiceScopeFactory scopeFactory, IConfiguration configuration)
    {
        _logger = logger;
        _scopeFactory = scopeFactory;
        _configuration = configuration;
        InitializeRabbitMQ();
    }

    private void InitializeRabbitMQ()
    {
        var hostName = _configuration["RabbitMQ:HostName"] ?? "localhost";
        var factory = new ConnectionFactory() { HostName = hostName };
        
        int retryCount = 0;
        const int maxRetries = 10;
        
        while (retryCount < maxRetries)
        {
            try
            {
                _connection = factory.CreateConnection();
                _channel = _connection.CreateModel();
                _channel.QueueDeclare(queue: QueueName, durable: true, exclusive: false, autoDelete: false, arguments: null);
                _logger.LogInformation("RabbitMQ Consumer initialized successfully after {Retries} retries.", retryCount);
                return;
            }
            catch (Exception)
            {
                retryCount++;
                _logger.LogWarning("RabbitMQ not ready yet. Retrying {RetryCount}/{MaxRetries} in 5s...", retryCount, maxRetries);
                Thread.Sleep(5000);
            }
        }
        
        _logger.LogError("Could not connect to RabbitMQ after {MaxRetries} attempts.", maxRetries);
    }

    protected override Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (_channel == null) return Task.CompletedTask;

        stoppingToken.ThrowIfCancellationRequested();

        var consumer = new EventingBasicConsumer(_channel);
        consumer.Received += async (model, ea) =>
        {
            var body = ea.Body.ToArray();
            var message = Encoding.UTF8.GetString(body);
            
            try
            {
                var listingData = JsonSerializer.Deserialize<Listing>(message, new JsonSerializerOptions 
                { 
                    PropertyNameCaseInsensitive = true 
                });

                if (listingData != null)
                {
                    using var scope = _scopeFactory.CreateScope();
                    var db = scope.ServiceProvider.GetRequiredService<BuyGuardianContext>();
                    
                    // Ensure Seller exists
                    var sellerUsername = listingData.Seller?.Username;
                    var seller = await db.Sellers.FirstOrDefaultAsync(s => s.OlxId == listingData.SellerId.ToString() || s.Username == sellerUsername);
                    if (seller == null)
                    {
                        seller = listingData.Seller ?? new Seller 
                        { 
                            Id = Guid.NewGuid(),
                            Username = "Unknown", 
                            OlxId = Guid.NewGuid().ToString() // Fallback if seller info is missing
                        };
                        db.Sellers.Add(seller);
                        await db.SaveChangesAsync(stoppingToken);
                    }

                    listingData.SellerId = seller.Id;
                    listingData.Seller = null; // Prevent EF from trying to re-add the seller object

                    // Add or Update Listing
                    var existingListing = await db.Listings.FirstOrDefaultAsync(l => l.ItemId == listingData.ItemId);
                    if (existingListing != null)
                    {
                        // Update existing
                        existingListing.Title = listingData.Title;
                        existingListing.Description = listingData.Description;
                        existingListing.Price = listingData.Price;
                        existingListing.RawMetadata = listingData.RawMetadata;
                        existingListing.TrustScore = listingData.TrustScore;
                        existingListing.ScrapedAt = listingData.ScrapedAt;
                        db.Listings.Update(existingListing);
                    }
                    else
                    {
                        db.Listings.Add(listingData);
                    }

                    await db.SaveChangesAsync(stoppingToken);
                    
                    _logger.LogInformation($"Processed listing from scraper: {listingData.ItemId}");
                    _channel.BasicAck(deliveryTag: ea.DeliveryTag, multiple: false);
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error processing message from RabbitMQ");
                // In production, you might want to move this to a dead-letter queue
                _channel.BasicNack(deliveryTag: ea.DeliveryTag, multiple: false, requeue: true);
            }
        };

        _channel.BasicConsume(queue: QueueName, autoAck: false, consumer: consumer);
        return Task.CompletedTask;
    }

    public override void Dispose()
    {
        _channel?.Close();
        _connection?.Close();
        base.Dispose();
    }
}
