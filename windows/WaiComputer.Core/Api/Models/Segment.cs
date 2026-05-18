using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

public sealed record Segment(
    string Id,
    string? Speaker,
    [property: JsonPropertyName("raw_label")] string? RawLabel,
    [property: JsonPropertyName("person_id")] string? PersonId,
    [property: JsonPropertyName("display_name")] string? DisplayName,
    [property: JsonPropertyName("auto_assigned")] bool AutoAssigned,
    [property: JsonPropertyName("match_confidence")] double? MatchConfidence,
    string Content,
    [property: JsonPropertyName("start_ms")] long? StartMs,
    [property: JsonPropertyName("end_ms")] long? EndMs,
    double? Confidence)
{
    public long? DurationMs => (StartMs is { } s && EndMs is { } e) ? e - s : null;

    public string FormattedTimestamp =>
        StartMs is { } ms
            ? $"{ms / 60000:D2}:{(ms / 1000) % 60:D2}"
            : "--:--";
}

/// <summary>
/// Segment emitted by the realtime transcription pipeline before it's been
/// persisted on the server. The <see cref="IsFinal"/> flag distinguishes
/// interim partials from committed text.
/// </summary>
public sealed record LiveTranscriptSegment(
    string Text,
    string? Speaker,
    [property: JsonPropertyName("is_final")] bool IsFinal,
    [property: JsonPropertyName("start_ms")] long StartMs,
    [property: JsonPropertyName("end_ms")] long EndMs,
    double Confidence);

public sealed record AssignSpeakerRequest(
    [property: JsonPropertyName("raw_label")] string RawLabel,
    [property: JsonPropertyName("person_id")] string? PersonId,
    [property: JsonPropertyName("new_display_name")] string? NewDisplayName);

public sealed record SaveTranscriptRequest(
    IReadOnlyList<LiveTranscriptSegment> Segments,
    [property: JsonPropertyName("duration_seconds")] int DurationSeconds);
