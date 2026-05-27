using System.Text.Json;
using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using Xunit;
using RecordingModel = WaiComputer.Core.Api.Models.Recording;

namespace WaiComputer.Core.Tests.Api;

public class ModelSerializationTests
{
    private static T RoundTrip<T>(T value)
    {
        var json = JsonSerializer.Serialize(value, WaiJson.Options);
        return JsonSerializer.Deserialize<T>(json, WaiJson.Options)!;
    }

    [Fact]
    public void RecordingStatusUsesSnakeCaseInJson()
    {
        var json = JsonSerializer.Serialize(RecordingStatus.PendingUpload, WaiJson.Options);
        json.Should().Be("\"pending_upload\"");
    }

    [Fact]
    public void RecordingTypeRoundTripsAllVariants()
    {
        foreach (var v in Enum.GetValues<RecordingType>())
        {
            RoundTrip(v).Should().Be(v);
        }
    }

    [Fact]
    public void RecordingDeserializesBackendShape()
    {
        const string body = """
        {
          "id": "rec-1",
          "title": "Standup",
          "type": "meeting",
          "language": "en",
          "folder_id": null,
          "status": "ready",
          "audio_url": "https://wai.computer/audio/rec-1.m4a",
          "duration_seconds": 187.5,
          "is_starred": true,
          "created_at": "2026-05-18T14:30:45.123456Z",
          "updated_at": "2026-05-18T14:31:00",
          "failure_code": null,
          "failure_message": null
        }
        """;
        var rec = JsonSerializer.Deserialize<RecordingModel>(body, WaiJson.Options)!;
        rec.Id.Should().Be("rec-1");
        rec.Type.Should().Be(RecordingType.Meeting);
        rec.Status.Should().Be(RecordingStatus.Ready);
        rec.DurationSeconds.Should().Be(187.5);
        rec.IsStarred.Should().BeTrue();
        rec.CreatedAt.Should().Be(new DateTimeOffset(2026, 5, 18, 14, 30, 45, 123, TimeSpan.Zero).AddTicks(4560));
        rec.UpdatedAt.ToUniversalTime().Should().Be(new DateTimeOffset(2026, 5, 18, 14, 31, 0, TimeSpan.Zero));
    }

    [Fact]
    public void RealtimeSessionDeserializes()
    {
        const string body = """
        {
          "provider": "deepgram",
          "token": "deepgram-temporary-token",
          "expires_in_seconds": 60,
          "sample_rate": 16000,
          "audio_format": "linear16",
          "language": "multi",
          "channels": 1,
          "model": "nova-3",
          "keep_alive_interval_seconds": 4,
          "commit_strategy": null,
          "no_verbatim": false,
          "websocket_url": "wss://api.deepgram.com/v1/listen?model=nova-3&language=multi",
          "auth_scheme": "bearer"
        }
        """;
        var cfg = JsonSerializer.Deserialize<RealtimeTranscriptionSessionConfig>(body, WaiJson.Options)!;
        cfg.Provider.Should().Be(RealtimeProvider.Deepgram);
        cfg.AuthScheme.Should().Be(AuthScheme.Bearer);
        cfg.SampleRate.Should().Be(16000);
    }

    [Fact]
    public void SegmentDurationCalc()
    {
        var seg = new Segment("s", null, null, null, null, false, null, "hello", 1000, 1750, null);
        seg.DurationMs.Should().Be(750);
        seg.FormattedTimestamp.Should().Be("00:01");
    }

    [Fact]
    public void ActionItemSerializesEnumLowercase()
    {
        var item = new ActionItem("i", "r", "do thing", ActionItemStatus.Open, ActionItemPriority.High, null, null,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var json = JsonSerializer.Serialize(item, WaiJson.Options);
        json.Should().Contain("\"status\":\"open\"");
        json.Should().Contain("\"priority\":\"high\"");
    }
}
