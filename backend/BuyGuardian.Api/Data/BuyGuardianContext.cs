using Microsoft.EntityFrameworkCore;
using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Data;

public class BuyGuardianContext : DbContext
{
    public BuyGuardianContext(DbContextOptions<BuyGuardianContext> options) : base(options)
    {
    }

    public DbSet<Listing> Listings => Set<Listing>();
    public DbSet<Seller> Sellers => Set<Seller>();
    public DbSet<Product> Products => Set<Product>();
    public DbSet<Category> Categories => Set<Category>();
    public DbSet<PriceHistory> PriceHistories => Set<PriceHistory>();
    public DbSet<SearchQuery> SearchQueries => Set<SearchQuery>();
    public DbSet<AnalysisVote> AnalysisVotes => Set<AnalysisVote>();
    public DbSet<PriceAlert> PriceAlerts => Set<PriceAlert>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.HasPostgresExtension("vector");

        modelBuilder.Entity<Listing>(entity =>
        {
            entity.HasIndex(e => e.ItemId).IsUnique();
            entity.Property(e => e.RawMetadata).HasColumnType("jsonb");
            
            entity.HasOne(e => e.Seller)
                .WithMany(s => s.Listings)
                .HasForeignKey(e => e.SellerId);

            entity.HasOne(e => e.Product)
                .WithMany(p => p.Listings)
                .HasForeignKey(e => e.ProductId);
        });

        modelBuilder.Entity<Seller>(entity =>
        {
            entity.HasIndex(e => e.OlxId).IsUnique();
        });

        modelBuilder.Entity<Product>(entity =>
        {
            entity.HasIndex(e => new { e.CanonicalName, e.CategoryId }).IsUnique();
            entity.Property(e => e.Attributes).HasColumnType("jsonb");
            entity.Property(e => e.ProductVector).HasColumnType("vector(768)");
            entity.HasIndex(e => e.CategoryName);
        });

        modelBuilder.Entity<Category>(entity =>
        {
            entity.HasIndex(e => e.Name).IsUnique();
            entity.Property(e => e.ExtractSchema).HasColumnType("jsonb");
        });

        modelBuilder.Entity<PriceHistory>(entity =>
        {
            entity.HasOne(e => e.Listing)
                .WithMany(l => l.PriceHistories)
                .HasForeignKey(e => e.ListingId);
        });

        modelBuilder.Entity<SearchQuery>(entity =>
        {
            entity.HasIndex(e => e.QueryTerm).IsUnique();
        });

        modelBuilder.Entity<AnalysisVote>(entity =>
        {
            // One vote per fingerprint per listing
            entity.HasIndex(e => new { e.ItemId, e.UserFingerprint }).IsUnique();
            entity.HasIndex(e => e.ItemId);
            entity.Property(e => e.Vote).HasMaxLength(4);
            entity.Property(e => e.UserFingerprint).HasMaxLength(64);
        });

        modelBuilder.Entity<PriceAlert>(entity =>
        {
            entity.HasIndex(e => e.ItemId);
            entity.HasIndex(e => e.UserFingerprint);
            entity.HasIndex(e => e.IsActive);
        });
    }
}
