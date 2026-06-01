namespace WaiComputer.Core.Recordings;

/// <summary>Which audio sources the recording header should advertise as live.</summary>
public enum SystemAudioHeaderIndicator
{
    MicAndSystem,
    SystemAudioStarting,
    SystemAudioDegraded,
    MicrophoneOnly,
}

/// <summary>
/// Pure policy for system-audio capture warnings, ported from the macOS
/// <c>SystemAudioWarningPolicy</c>. The capture layer owns stall detection;
/// absence of audible samples alone is NOT a warning — a freshly-started call can
/// be silent while the tap is healthy.
/// </summary>
public static class SystemAudioWarningPolicy
{
    /// <summary>Show the capture warning only when the tap has actually stalled.</summary>
    public static bool ShouldShowCaptureWarning(bool systemAudioStalled, bool systemAudioReceivedAny)
    {
        _ = systemAudioReceivedAny; // intentionally ignored, matching Mac
        return systemAudioStalled;
    }

    public static SystemAudioHeaderIndicator HeaderIndicator(bool requestedSystemAudio, bool hasSystemAudio, bool hasWarning)
    {
        if (!requestedSystemAudio)
        {
            return SystemAudioHeaderIndicator.MicrophoneOnly;
        }
        if (hasWarning)
        {
            return SystemAudioHeaderIndicator.SystemAudioDegraded;
        }
        return hasSystemAudio
            ? SystemAudioHeaderIndicator.MicAndSystem
            : SystemAudioHeaderIndicator.SystemAudioStarting;
    }
}
