using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

public sealed record Summary(
    [property: JsonPropertyName("summary")] string Text,
    [property: JsonPropertyName("key_points")] IReadOnlyList<string> KeyPoints,
    IReadOnlyList<string> Decisions,
    IReadOnlyList<string> Topics,
    [property: JsonPropertyName("people_mentioned")] IReadOnlyList<string> PeopleMentioned,
    string? Sentiment);

[JsonConverter(typeof(JsonStringEnumConverter<ActionItemStatus>))]
public enum ActionItemStatus
{
    [JsonStringEnumMemberName("open")] Open,
    [JsonStringEnumMemberName("done")] Done,
    [JsonStringEnumMemberName("cancelled")] Cancelled,
}

[JsonConverter(typeof(JsonStringEnumConverter<ActionItemPriority>))]
public enum ActionItemPriority
{
    [JsonStringEnumMemberName("low")] Low,
    [JsonStringEnumMemberName("medium")] Medium,
    [JsonStringEnumMemberName("high")] High,
}

public sealed record ActionItem(
    string Id,
    [property: JsonPropertyName("recording_id")] string RecordingId,
    string Text,
    ActionItemStatus Status,
    ActionItemPriority Priority,
    string? Assignee,
    [property: JsonPropertyName("due_date")] DateTimeOffset? DueDate,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt);

public sealed record UpdateActionItemRequest(ActionItemStatus? Status, ActionItemPriority? Priority);

public sealed record Highlight(
    string Id,
    [property: JsonPropertyName("recording_id")] string RecordingId,
    string Text,
    [property: JsonPropertyName("start_ms")] long? StartMs,
    [property: JsonPropertyName("end_ms")] long? EndMs);

public sealed record SpeakerStat(
    [property: JsonPropertyName("raw_label")] string RawLabel,
    [property: JsonPropertyName("person_id")] string? PersonId,
    [property: JsonPropertyName("display_name")] string DisplayName,
    [property: JsonPropertyName("total_ms")] long TotalMs,
    [property: JsonPropertyName("segment_count")] int SegmentCount);
