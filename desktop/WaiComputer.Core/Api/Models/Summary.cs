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
    [JsonStringEnumMemberName("pending")] Pending,
    [JsonStringEnumMemberName("in_progress")] InProgress,
    [JsonStringEnumMemberName("completed")] Completed,
    [JsonStringEnumMemberName("cancelled")] Cancelled,
}

[JsonConverter(typeof(JsonStringEnumConverter<ActionItemPriority>))]
public enum ActionItemPriority
{
    [JsonStringEnumMemberName("low")] Low,
    [JsonStringEnumMemberName("medium")] Medium,
    [JsonStringEnumMemberName("high")] High,
}

/// <summary>
/// Mirrors the backend <c>ActionItemResponse</c>
/// (backend/app/api/routes/action_items.py): id, recording_id, task, owner?,
/// due_date?, priority?, status, source, created_at. <c>due_date</c> is a bare
/// string (may be a date-only value), <c>priority</c> is nullable, and there is
/// no <c>updated_at</c> — matching these exactly is required or list/update
/// calls throw under the no-fallback JSON policy.
/// </summary>
public sealed record ActionItem(
    string Id,
    [property: JsonPropertyName("recording_id")] string RecordingId,
    string Task,
    string? Owner,
    [property: JsonPropertyName("due_date")] string? DueDate,
    ActionItemPriority? Priority,
    ActionItemStatus Status,
    string Source,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

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
