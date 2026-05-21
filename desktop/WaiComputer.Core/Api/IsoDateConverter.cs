using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api;

/// <summary>
/// Parses ISO-8601 timestamps from the WaiComputer backend.
/// Accepts both tz-aware (<c>2026-05-18T14:30:45.123456Z</c>,
/// <c>2026-05-18T14:30:45.123+02:00</c>) and tz-naive
/// (<c>2026-05-18T14:30:45.123456</c>) forms — Python's <c>datetime.isoformat()</c>
/// drops the timezone when called on a naive datetime, which the backend
/// occasionally emits. Naive values are interpreted as UTC.
/// </summary>
public sealed class IsoDateTimeOffsetConverter : JsonConverter<DateTimeOffset>
{
    public override DateTimeOffset Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        var s = reader.GetString();
        if (string.IsNullOrEmpty(s))
        {
            throw new JsonException("Expected ISO-8601 datetime string, got empty/null.");
        }

        if (DateTimeOffset.TryParse(
                s,
                CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
                out var dto))
        {
            return dto;
        }

        if (DateTime.TryParse(
                s,
                CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
                out var dt))
        {
            return new DateTimeOffset(DateTime.SpecifyKind(dt, DateTimeKind.Utc), TimeSpan.Zero);
        }

        throw new JsonException($"Unparseable ISO-8601 datetime: '{s}'");
    }

    public override void Write(Utf8JsonWriter writer, DateTimeOffset value, JsonSerializerOptions options)
    {
        // Round-trip with microsecond precision: matches Python's .isoformat() output.
        writer.WriteStringValue(value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffK", CultureInfo.InvariantCulture));
    }
}

/// <summary>
/// Convenience nullable wrapper for <see cref="IsoDateTimeOffsetConverter"/>.
/// </summary>
public sealed class NullableIsoDateTimeOffsetConverter : JsonConverter<DateTimeOffset?>
{
    private static readonly IsoDateTimeOffsetConverter Inner = new();

    public override DateTimeOffset? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.Null)
        {
            return null;
        }
        return Inner.Read(ref reader, typeof(DateTimeOffset), options);
    }

    public override void Write(Utf8JsonWriter writer, DateTimeOffset? value, JsonSerializerOptions options)
    {
        if (value is null)
        {
            writer.WriteNullValue();
        }
        else
        {
            Inner.Write(writer, value.Value, options);
        }
    }
}
