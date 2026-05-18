using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

public sealed record SearchHit(
    [property: JsonPropertyName("recording_id")] string RecordingId,
    string Title,
    string? Snippet,
    [property: JsonPropertyName("matched_at_ms")] long? MatchedAtMs,
    double? Score);

public sealed record SearchResponse(string Query, IReadOnlyList<SearchHit> Results);
