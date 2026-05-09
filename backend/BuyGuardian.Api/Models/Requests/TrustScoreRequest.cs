using BuyGuardian.Api.Models;

namespace BuyGuardian.Api.Models.Requests;

public class TrustScoreRequest
{
    public TrustScoreListingPayload Listing { get; set; } = new();
    public double? Label { get; set; }
    public bool? Retrain { get; set; }
}

public class TrustScoreListingPayload
{
    public Guid Id { get; set; }
    public string ItemId { get; set; } = string.Empty;
    public Guid SellerId { get; set; }
    public Guid? ProductId { get; set; }
    public string Title { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public decimal Price { get; set; }
    public Dictionary<string, object> RawMetadata { get; set; } = new();
    public bool IsActive { get; set; }
    public bool IsNew { get; set; }
    public DateTime ScrapedAt { get; set; }

    public static TrustScoreListingPayload FromListing(Listing listing)
    {
        return new TrustScoreListingPayload
        {
            Id = listing.Id,
            ItemId = listing.ItemId,
            SellerId = listing.SellerId,
            ProductId = listing.ProductId,
            Title = listing.Title,
            Description = listing.Description,
            Price = listing.Price,
            RawMetadata = listing.RawMetadata ?? new Dictionary<string, object>(),
            IsActive = listing.IsActive,
            IsNew = listing.IsNew,
            ScrapedAt = listing.ScrapedAt,
        };
    }
}
