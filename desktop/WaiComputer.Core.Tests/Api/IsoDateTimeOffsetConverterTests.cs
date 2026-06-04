using System.Text.Json;
using FluentAssertions;
using WaiComputer.Core.Api;
using Xunit;

namespace WaiComputer.Core.Tests.Api;

public class IsoDateTimeOffsetConverterTests
{
    private static T RoundTrip<T>(T value)
    {
        var json = JsonSerializer.Serialize(value, WaiJson.Options);
        return JsonSerializer.Deserialize<T>(json, WaiJson.Options)!;
    }

    [Theory]
    [InlineData("\"2026-05-18T14:30:45.123456Z\"", "2026-05-18T14:30:45.1234560+00:00")]
    [InlineData("\"2026-05-18T14:30:45.123Z\"", "2026-05-18T14:30:45.1230000+00:00")]
    [InlineData("\"2026-05-18T14:30:45Z\"", "2026-05-18T14:30:45.0000000+00:00")]
    public void ParsesTimezoneAwareForms(string json, string expected)
    {
        var parsed = JsonSerializer.Deserialize<DateTimeOffset>(json, WaiJson.Options);
        parsed.ToUniversalTime().Should().Be(DateTimeOffset.Parse(expected));
    }

    [Theory]
    [InlineData("\"2026-05-18T14:30:45.123456\"", "2026-05-18T14:30:45.1234560+00:00")]
    [InlineData("\"2026-05-18T14:30:45\"", "2026-05-18T14:30:45.0000000+00:00")]
    public void ParsesTimezoneNaiveAsUtc(string json, string expected)
    {
        var parsed = JsonSerializer.Deserialize<DateTimeOffset>(json, WaiJson.Options);
        parsed.ToUniversalTime().Should().Be(DateTimeOffset.Parse(expected));
    }

    [Theory]
    [InlineData("\"2026-05-18T16:30:45.123+02:00\"", "2026-05-18T14:30:45.123+00:00")]
    [InlineData("\"2026-05-18T08:30:45-06:00\"", "2026-05-18T14:30:45+00:00")]
    public void NormalizesNonUtcOffsetsToUtc(string json, string expected)
    {
        var parsed = JsonSerializer.Deserialize<DateTimeOffset>(json, WaiJson.Options);
        parsed.ToUniversalTime().Should().Be(DateTimeOffset.Parse(expected));
    }

    [Fact]
    public void RejectsGarbage()
    {
        var act = () => JsonSerializer.Deserialize<DateTimeOffset>("\"not a date\"", WaiJson.Options);
        act.Should().Throw<JsonException>();
    }

    [Fact]
    public void RejectsEmptyString()
    {
        var act = () => JsonSerializer.Deserialize<DateTimeOffset>("\"\"", WaiJson.Options);
        act.Should().Throw<JsonException>();
    }

    [Fact]
    public void NullableSurvivesNull()
    {
        var parsed = JsonSerializer.Deserialize<DateTimeOffset?>("null", WaiJson.Options);
        parsed.Should().BeNull();
    }

    [Fact]
    public void RoundTripPreservesMicroseconds()
    {
        var original = new DateTimeOffset(2026, 5, 18, 14, 30, 45, 123, TimeSpan.Zero).AddTicks(4560);
        var rt = RoundTrip(original);
        rt.Ticks.Should().Be(original.Ticks);
    }
}
