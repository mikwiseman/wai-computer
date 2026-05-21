using System.Text.Json;
using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api;

/// <summary>
/// Centralised <see cref="JsonSerializerOptions"/> for WaiComputer DTOs.
/// All requests / responses go through this — never construct ad-hoc options
/// elsewhere, or snake_case mapping + ISO date parsing will drift.
/// </summary>
public static class WaiJson
{
    public static readonly JsonSerializerOptions Options = CreateOptions();

    private static JsonSerializerOptions CreateOptions()
    {
        var o = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            DictionaryKeyPolicy = JsonNamingPolicy.SnakeCaseLower,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            ReadCommentHandling = JsonCommentHandling.Skip,
            AllowTrailingCommas = false,
            PropertyNameCaseInsensitive = false,
        };
        o.Converters.Add(new IsoDateTimeOffsetConverter());
        o.Converters.Add(new NullableIsoDateTimeOffsetConverter());
        o.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower));
        return o;
    }
}
