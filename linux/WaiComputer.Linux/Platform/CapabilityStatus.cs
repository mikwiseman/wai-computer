namespace WaiComputer.Linux.Platform;

public enum LinuxCapabilityState
{
    Supported,
    PermissionRequired,
    Unsupported,
}

public sealed record CapabilityStatus(
    string Name,
    LinuxCapabilityState State,
    string Detail,
    string? RecoveryAction = null)
{
    public bool IsSupported => State == LinuxCapabilityState.Supported;
}

public sealed record LinuxCapabilityReport(
    CapabilityStatus MicrophoneAudio,
    CapabilityStatus SystemAudio,
    CapabilityStatus GlobalHotkey,
    CapabilityStatus TextInsertion,
    CapabilityStatus SessionStorage,
    CapabilityStatus DesktopIntegration)
{
    public IReadOnlyList<CapabilityStatus> All =>
    [
        MicrophoneAudio,
        SystemAudio,
        GlobalHotkey,
        TextInsertion,
        SessionStorage,
        DesktopIntegration,
    ];
}
