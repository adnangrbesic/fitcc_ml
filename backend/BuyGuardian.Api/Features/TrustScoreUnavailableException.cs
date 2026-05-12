namespace BuyGuardian.Api.Features;

public class TrustScoreUnavailableException : Exception
{
    public TrustScoreUnavailableException(string message) : base(message)
    {
    }
}
