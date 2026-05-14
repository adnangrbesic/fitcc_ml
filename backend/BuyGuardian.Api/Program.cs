using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Data;
using BuyGuardian.Api.Interfaces;
using BuyGuardian.Api.Services;
using System.Text.Json.Serialization;
using Npgsql;

var builder = WebApplication.CreateBuilder(args);

// AppContext.SetSwitch("Npgsql.EnableLegacyTimestampBehavior", true);

// Npgsql configuration is now handled via NpgsqlDataSourceBuilder
// to avoid the obsolete GlobalTypeMapper.

builder.Services.AddControllers()
    .AddJsonOptions(options =>
    {
        options.JsonSerializerOptions.ReferenceHandler = ReferenceHandler.IgnoreCycles;
        options.JsonSerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull;
    });

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddSignalR();

// Database
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection");
var dataSourceBuilder = new NpgsqlDataSourceBuilder(connectionString);
dataSourceBuilder.EnableDynamicJson();
dataSourceBuilder.UseVector();
var dataSource = dataSourceBuilder.Build();

builder.Services.AddDbContext<BuyGuardianContext>(options =>
    options.UseNpgsql(dataSource, o => o.UseVector()));

builder.Services.AddHttpClient();


// MediatR
builder.Services.AddMediatR(cfg => cfg.RegisterServicesFromAssembly(typeof(Program).Assembly));

// Redis
var redisConfig = builder.Configuration.GetSection("Redis:Configuration").Value ?? "localhost:6379";
builder.Services.AddSingleton<StackExchange.Redis.IConnectionMultiplexer>(StackExchange.Redis.ConnectionMultiplexer.Connect(redisConfig));
builder.Services.AddScoped<ICacheService, RedisCacheService>();

// Services
builder.Services.AddHttpClient<IEmbeddingService, EmbeddingService>();
builder.Services.AddScoped<IProductMatcher, ProductMatcher>();

// ML Anomaly Detection Service (Python microservice)
builder.Services.AddHttpClient<IMlService, MlService>();

// RabbitMQ Hosted Service
builder.Services.AddHostedService<ListingConsumer>();

// CORS - Explicitly allow Chrome/Edge extensions and local dev origins
builder.Services.AddCors(options =>
{
    options.AddPolicy("ExtensionCors", policy =>
    {
        policy
            // Chrome/Edge/Opera extension origins (chrome-extension://*, moz-extension://*, etc.)
            .SetIsOriginAllowed(origin =>
                origin.StartsWith("chrome-extension://") ||
                origin.StartsWith("moz-extension://") ||
                origin.StartsWith("http://localhost") ||
                origin.StartsWith("https://localhost") ||
                origin.StartsWith("http://127.0.0.1") ||
                string.IsNullOrEmpty(origin) // some extension requests come with no Origin
            )
            .AllowAnyMethod()
            .AllowAnyHeader()
            .AllowCredentials();
    });
});

var app = builder.Build();

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

// CORS mora biti PRIJE HttpsRedirection jer redirect ne prenosi CORS headere
app.UseCors("ExtensionCors");
app.UseAuthorization();
app.MapControllers();
app.MapHub<BuyGuardian.Api.Hubs.AnalysisHub>("/hubs/analysis");

using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<BuyGuardianContext>();
    try 
    {
        db.Database.Migrate();
    }
    catch (Exception ex)
    {
        var logger = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();
        logger.LogError(ex, "An error occurred while migrating the database.");
    }
}

app.Run();

