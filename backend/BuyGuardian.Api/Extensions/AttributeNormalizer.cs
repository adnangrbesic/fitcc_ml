namespace BuyGuardian.Api.Extensions;

/// <summary>
/// Shared utility for normalizing PostgreSQL JSONB attributes into
/// plain .NET dictionaries that serialize correctly to JSON.
/// </summary>
public static class AttributeNormalizer
{
    /// <summary>
    /// Unwraps System.Text.Json.JsonElement values from JSONB into
    /// plain .NET types (string, int, double, bool).
    /// Returns an empty dictionary if input is null.
    /// </summary>
    public static Dictionary<string, object> Normalize(Dictionary<string, object>? attrs)
    {
        if (attrs == null || attrs.Count == 0)
            return new Dictionary<string, object>();

        var result = new Dictionary<string, object>();
        foreach (var kv in attrs)
        {
            result[kv.Key] = UnwrapJsonElement(kv.Value);
        }
        return result;
    }

    private static object UnwrapJsonElement(object value)
    {
        if (value is System.Text.Json.JsonElement je)
        {
            return je.ValueKind switch
            {
                System.Text.Json.JsonValueKind.String => je.GetString() ?? "",
                System.Text.Json.JsonValueKind.Number => je.TryGetInt32(out var i) ? (object)i : je.GetDouble(),
                System.Text.Json.JsonValueKind.True => true,
                System.Text.Json.JsonValueKind.False => false,
                System.Text.Json.JsonValueKind.Null => "",
                _ => je.GetRawText()
            };
        }
        return value;
    }
}
