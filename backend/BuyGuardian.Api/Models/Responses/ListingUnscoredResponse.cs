using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuyGuardian.Api.Models.Responses
{
    public class ListingUnscoredResponse
    {
        public Guid Id { get; set; }
        public int AccountAgeMonths { get; set; }
        public int PositiveFeedback { get; set; }
        public int NeutralFeedback { get; set; }
        public int NegativeFeedback { get; set; }
        public int SuccessfulDeliveries { get; set; }
        public bool IsEmailVerified { get; set; }
        public bool IsPhoneVerified { get; set; }
        public bool IsAddressVerified { get; set; }
        public double SellerTrustScore { get; set; }

        [Column(TypeName = "decimal(18,2)")]
        public decimal Price { get; set; }
        public Dictionary<string, object> RawMetadata { get; set; } = new();
        public double? TrustScore { get; set; }
        public bool IsActive { get; set; } = true;
        public bool IsNew { get; set; }
        public DateTime ScrapedAt { get; set; } = DateTime.UtcNow;
    }
}
