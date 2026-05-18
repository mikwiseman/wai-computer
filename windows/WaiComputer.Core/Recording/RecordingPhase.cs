namespace WaiComputer.Core.Recording;

public enum RecordingPhase
{
    Idle,
    Preparing,
    Recording,
    Finalizing,
}

public enum RecordingInputSource
{
    /// <summary>Microphone only.</summary>
    Microphone,
    /// <summary>Microphone + system-audio loopback (the default).</summary>
    Dual,
}
