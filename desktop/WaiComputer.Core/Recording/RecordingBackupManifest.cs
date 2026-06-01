using System.Text.Json.Serialization;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Recordings;

/// <summary>Sync lifecycle of a locally-backed recording (drives the upload coordinator's retry decisions).</summary>
[JsonConverter(typeof(JsonStringEnumConverter<RecordingBackupSyncState>))]
public enum RecordingBackupSyncState
{
    [JsonStringEnumMemberName("local_recording")] LocalRecording,
    [JsonStringEnumMemberName("local_ready")] LocalReady,
    [JsonStringEnumMemberName("uploading")] Uploading,
    [JsonStringEnumMemberName("server_processing")] ServerProcessing,
    [JsonStringEnumMemberName("retryable_failure")] RetryableFailure,
    [JsonStringEnumMemberName("permanent_failure")] PermanentFailure,
    [JsonStringEnumMemberName("auth_required")] AuthRequired,
}

/// <summary>
/// On-disk metadata for a pending/failed recording awaiting upload. Mirrors
/// the Swift <c>RecordingBackupManifest</c> field-for-field so the macOS
/// directory layout reads identically on Windows when users migrate.
/// </summary>
public sealed record RecordingBackupManifest(
    [property: JsonPropertyName("recording_id")] Guid RecordingId,
    string Title,
    [property: JsonPropertyName("recording_type")] RecordingType RecordingType,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("duration_seconds")] double DurationSeconds,
    [property: JsonPropertyName("segment_count")] int SegmentCount,
    string Transcript,
    [property: JsonPropertyName("last_error_message")] string? LastErrorMessage,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("has_audio_file")] bool HasAudioFile,
    [property: JsonPropertyName("is_permanent_failure")] bool IsPermanentFailure,
    [property: JsonPropertyName("requires_authentication")] bool RequiresAuthentication,
    [property: JsonPropertyName("sync_state")] RecordingBackupSyncState SyncState = RecordingBackupSyncState.LocalReady,
    [property: JsonPropertyName("server_job_id")] string? ServerJobId = null,
    [property: JsonPropertyName("last_sync_attempt_at")] DateTimeOffset? LastSyncAttemptAt = null,
    [property: JsonPropertyName("sync_attempt_count")] int SyncAttemptCount = 0,
    [property: JsonPropertyName("last_failure_code")] string? LastFailureCode = null);
