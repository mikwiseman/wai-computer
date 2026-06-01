using WaiComputer.Core.Audio;

namespace WaiComputer.Core.Recordings;

/// <summary>Platform mic-permission gate. Windows/Linux have no privacy prompt (always granted).</summary>
public interface IMicrophonePermission
{
    Task<bool> EnsureGrantedAsync(CancellationToken ct);
}

/// <summary>Builds the platform <see cref="DualAudioCapture"/> for a chosen input source.</summary>
public interface IAudioCaptureFactory
{
    /// <param name="requestsSystemAudio">True when the user asked for system-audio capture (drives the header indicator even if the tap never produces audio).</param>
    DualAudioCapture Create(RecordingInputSource source, out bool requestsSystemAudio);
}

/// <summary>Surfaces a recovery notice to the user (replaces macOS NotificationCenter recovery posts).</summary>
public interface IRecoveryNoticeSink
{
    void Post(string message);
}

/// <summary>Realtime transcription connectivity as the recording UI should show it.</summary>
public enum RealtimeConnectionState
{
    Connected,
    Reconnecting,
    Offline,
}

/// <summary>
/// Immutable snapshot of a <see cref="RecordingSession"/>, raised on every
/// observable change. The UI thread-marshals it — Core stays thread-agnostic.
/// </summary>
public sealed record RecordingSessionState(
    RecordingPhase Phase,
    bool IsPaused,
    int DurationSeconds,
    bool RequestedSystemAudio,
    bool HasSystemAudio,
    bool LiveTranscriptionOffline,
    RealtimeConnectionState ConnectionState,
    int ReconnectAttempt,
    int ReconnectMaxAttempts,
    string? SystemAudioWarning,
    string CommittedTranscript,
    string InterimTranscript,
    string? CurrentRecordingId,
    string? Error)
{
    public static RecordingSessionState Idle { get; } = new(
        RecordingPhase.Idle, IsPaused: false, DurationSeconds: 0, RequestedSystemAudio: false,
        HasSystemAudio: false, LiveTranscriptionOffline: false, ConnectionState: RealtimeConnectionState.Connected,
        ReconnectAttempt: 0, ReconnectMaxAttempts: 0, SystemAudioWarning: null,
        CommittedTranscript: "", InterimTranscript: "", CurrentRecordingId: null, Error: null);

    /// <summary>Header indicator derived from the requested/actual system-audio state + warning.</summary>
    public SystemAudioHeaderIndicator HeaderIndicator
        => SystemAudioWarningPolicy.HeaderIndicator(RequestedSystemAudio, HasSystemAudio, SystemAudioWarning is not null);
}
