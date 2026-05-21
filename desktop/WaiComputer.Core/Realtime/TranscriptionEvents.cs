using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

public abstract record TranscriptionEvent
{
    public sealed record Connected : TranscriptionEvent;
    public sealed record Disconnected(string? Reason) : TranscriptionEvent;
    public sealed record Transcript(LiveTranscriptSegment Segment) : TranscriptionEvent;
    public sealed record Reconnecting(int Attempt, int MaxAttempts) : TranscriptionEvent;
    public sealed record Reconnected : TranscriptionEvent;
    public sealed record ReconnectionFailed(Exception? Cause) : TranscriptionEvent;
    public sealed record ProviderWarning(string Code, string Message) : TranscriptionEvent;
}

/// <summary>
/// Documented provider-side error codes that bubble out as
/// <see cref="TranscriptionEvent.ProviderWarning"/> events.
/// </summary>
public static class TranscriptionErrorCodes
{
    public const string AuthError = "auth_error";
    public const string QuotaExceeded = "quota_exceeded";
    public const string CommitThrottled = "commit_throttled";
    public const string UnacceptedTerms = "unaccepted_terms";
    public const string RateLimited = "rate_limited";
    public const string QueueOverflow = "queue_overflow";
    public const string ResourceExhausted = "resource_exhausted";
    public const string SessionTimeLimitExceeded = "session_time_limit_exceeded";
    public const string InputError = "input_error";
    public const string ChunkSizeExceeded = "chunk_size_exceeded";
    public const string InsufficientAudioActivity = "insufficient_audio_activity";
    public const string TranscriberError = "transcriber_error";
    public const string GenericError = "error";

    public static readonly IReadOnlySet<string> AllKnownCodes = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        AuthError, QuotaExceeded, CommitThrottled, UnacceptedTerms, RateLimited,
        QueueOverflow, ResourceExhausted, SessionTimeLimitExceeded, InputError,
        ChunkSizeExceeded, InsufficientAudioActivity, TranscriberError, GenericError,
    };

    public static readonly IReadOnlySet<string> Fatal = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        AuthError, UnacceptedTerms, SessionTimeLimitExceeded,
    };
}
