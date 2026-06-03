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
    public void ActionItemStatusUsesBackendWireValues()
    {
        JsonSerializer.Serialize(ActionItemStatus.Pending, WaiJson.Options).Should().Be("\"pending\"");
        JsonSerializer.Serialize(ActionItemStatus.InProgress, WaiJson.Options).Should().Be("\"in_progress\"");
        JsonSerializer.Serialize(ActionItemStatus.Completed, WaiJson.Options).Should().Be("\"completed\"");
        JsonSerializer.Serialize(ActionItemStatus.Cancelled, WaiJson.Options).Should().Be("\"cancelled\"");

        JsonSerializer.Deserialize<ActionItemStatus>("\"pending\"", WaiJson.Options).Should().Be(ActionItemStatus.Pending);
        JsonSerializer.Deserialize<ActionItemStatus>("\"in_progress\"", WaiJson.Options).Should().Be(ActionItemStatus.InProgress);
        JsonSerializer.Deserialize<ActionItemStatus>("\"completed\"", WaiJson.Options).Should().Be(ActionItemStatus.Completed);
        JsonSerializer.Deserialize<ActionItemStatus>("\"cancelled\"", WaiJson.Options).Should().Be(ActionItemStatus.Cancelled);
    }

    [Fact]
    public void ActionItemDeserializesBackendShape()
    {
        // Backend ActionItemResponse with null owner + null priority — the case
        // that crashed the old DTO (non-nullable Priority enum, "task"/"owner" mismatch).
        const string body = """
        {
          "id": "ai-1",
          "recording_id": "rec-1",
          "task": "Send the report",
          "owner": null,
          "due_date": "2026-06-01",
          "priority": null,
          "status": "pending",
          "source": "ai",
          "created_at": "2026-05-18T14:30:45Z"
        }
        """;
        var item = JsonSerializer.Deserialize<ActionItem>(body, WaiJson.Options)!;
        item.Id.Should().Be("ai-1");
        item.RecordingId.Should().Be("rec-1");
        item.Task.Should().Be("Send the report");
        item.Owner.Should().BeNull();
        item.DueDate.Should().Be("2026-06-01");
        item.Priority.Should().BeNull();
        item.Status.Should().Be(ActionItemStatus.Pending);
        item.Source.Should().Be("ai");
        item.CreatedAt.Should().Be(new DateTimeOffset(2026, 5, 18, 14, 30, 45, TimeSpan.Zero));
    }

    [Fact]
    public void ActionItemSerializesPopulatedShape()
    {
        var item = new ActionItem("i", "r", "do thing", "Mik", "2026-06-01",
            ActionItemPriority.High, ActionItemStatus.InProgress, "manual", DateTimeOffset.UtcNow);
        var json = JsonSerializer.Serialize(item, WaiJson.Options);
        json.Should().Contain("\"status\":\"in_progress\"");
        json.Should().Contain("\"priority\":\"high\"");
        json.Should().Contain("\"task\":\"do thing\"");
        json.Should().Contain("\"owner\":\"Mik\"");
    }
}
