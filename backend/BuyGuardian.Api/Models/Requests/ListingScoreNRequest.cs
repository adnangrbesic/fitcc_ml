namespace BuyGuardian.Api.Models.Requests
{
    public class ListingScoreNRequest
    {
        public Dictionary<string, double> Score { get; set; } = new();
    }
}
