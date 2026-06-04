using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

/// <summary>
/// Mirrors the backend <c>SearchResultResponse</c>
/// (backend/app/api/routes/search.py): recording_id, recording_title?,
/// recording_type, segment_id, speaker?, content, start_ms?, end_ms?, score.
/// A search hit is a transcript <em>segment</em>, not a whole recording.
/// </summary>
public sealed record SearchHit(
    [property: JsonPropertyName("recording_id")] string RecordingId,
    [property: JsonPropertyName("recording_title")] string? RecordingTitle,
    [property: JsonPropertyName("recording_type")] RecordingType RecordingType,
    [property: JsonPropertyName("segment_id")] string SegmentId,
    string? Speaker,
    string Content,
    [property: JsonPropertyName("start_ms")] long? StartMs,
    [property: JsonPropertyName("end_ms")] long? EndMs,
    double Score);

/// <summary>Backend <c>SearchResponse</c>: the hit list plus a total count.</summary>
public sealed record SearchResponse(
    IReadOnlyList<SearchHit> Results,
    int Total);
