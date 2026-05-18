using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

[JsonConverter(typeof(JsonStringEnumConverter<RecordingType>))]
public enum RecordingType
{
    [JsonStringEnumMemberName("meeting")] Meeting,
    [JsonStringEnumMemberName("note")] Note,
    [JsonStringEnumMemberName("reflection")] Reflection,
}

[JsonConverter(typeof(JsonStringEnumConverter<RecordingStatus>))]
public enum RecordingStatus
{
    [JsonStringEnumMemberName("pending_upload")] PendingUpload,
    [JsonStringEnumMemberName("uploading")] Uploading,
    [JsonStringEnumMemberName("processing")] Processing,
    [JsonStringEnumMemberName("ready")] Ready,
    [JsonStringEnumMemberName("failed")] Failed,
}

public static class RecordingStatusExtensions
{
    public static string DisplayLabel(this RecordingStatus s) => s switch
    {
        RecordingStatus.PendingUpload => "Waiting to Sync",
        RecordingStatus.Uploading => "Syncing in Background",
        RecordingStatus.Processing => "Processing",
        RecordingStatus.Ready => "Ready",
        RecordingStatus.Failed => "Needs Attention",
        _ => "Unknown",
    };
}

public sealed record Recording(
    string Id,
    string Title,
    RecordingType Type,
    string Language,
    [property: JsonPropertyName("folder_id")] string? FolderId,
    RecordingStatus Status,
    [property: JsonPropertyName("audio_url")] string? AudioUrl,
    [property: JsonPropertyName("duration_seconds")] double DurationSeconds,
    [property: JsonPropertyName("is_starred")] bool IsStarred,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("failure_message")] string? FailureMessage);

public sealed record RecordingDetail(
    string Id,
    string Title,
    RecordingType Type,
    string Language,
    [property: JsonPropertyName("folder_id")] string? FolderId,
    RecordingStatus Status,
    [property: JsonPropertyName("audio_url")] string? AudioUrl,
    [property: JsonPropertyName("duration_seconds")] double DurationSeconds,
    [property: JsonPropertyName("is_starred")] bool IsStarred,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("failure_message")] string? FailureMessage,
    IReadOnlyList<Segment> Segments,
    Summary? Summary,
    [property: JsonPropertyName("action_items")] IReadOnlyList<ActionItem> ActionItems,
    IReadOnlyList<Highlight> Highlights,
    [property: JsonPropertyName("speaker_stats")] IReadOnlyList<SpeakerStat> SpeakerStats);

public sealed record CreateRecordingRequest(
    string? Title,
    RecordingType Type,
    string Language,
    [property: JsonPropertyName("folder_id")] string? FolderId);

public sealed record UpdateRecordingRequest(
    string? Title,
    RecordingType? Type,
    [property: JsonPropertyName("folder_id")] string? FolderId);

public sealed record RecordingShareLink(
    [property: JsonPropertyName("recording_id")] string RecordingId,
    string Token,
    string Url,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

public sealed record Folder(
    string Id,
    string Name,
    string? Color,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

public sealed record CreateFolderRequest(string Name, string? Color);
public sealed record UpdateFolderRequest(string? Name, string? Color);
