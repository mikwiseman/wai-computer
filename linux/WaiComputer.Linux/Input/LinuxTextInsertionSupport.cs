using WaiComputer.Linux.Platform;

namespace WaiComputer.Linux.Input;

public enum LinuxTextInsertionBackend
{
    WaylandPortals,
    X11ClipboardAndXTest,
    ManualPasteOnly,
}

public sealed record LinuxTextInsertionSupport(
    LinuxTextInsertionBackend Backend,
    string Detail,
    string? RecoveryAction = null)
{
    public bool IsAutomatic => Backend != LinuxTextInsertionBackend.ManualPasteOnly;

    public CapabilityStatus ToCapabilityStatus() => IsAutomatic
        ? new CapabilityStatus("Text insertion", LinuxCapabilityState.Supported, Detail)
        : new CapabilityStatus("Text insertion", LinuxCapabilityState.Unsupported, Detail, RecoveryAction);
}

public static class LinuxTextInsertionSupportDetector
{
    public static async Task<LinuxTextInsertionSupport> DetectAsync(
        LinuxDesktopEnvironment environment,
        PortalCapabilities portals,
        ToolProbe tools,
        CancellationToken ct = default)
    {
        if (environment.IsWayland)
        {
            if (portals.RemoteDesktopAvailable && portals.ClipboardAvailable)
            {
                return new LinuxTextInsertionSupport(LinuxTextInsertionBackend.WaylandPortals, "Wayland RemoteDesktop and Clipboard portals are available.");
            }

            return new LinuxTextInsertionSupport(
                LinuxTextInsertionBackend.ManualPasteOnly,
                "Wayland automatic paste requires both RemoteDesktop and Clipboard portals.",
                "Grant portal permissions on GNOME/KDE, or paste manually from the recovery clipboard copy.");
        }

        if (environment.IsX11)
        {
            var xclip = await tools.ExistsAsync("xclip", ct).ConfigureAwait(false);
            var xdotool = await tools.ExistsAsync("xdotool", ct).ConfigureAwait(false);
            if (xclip && xdotool)
            {
                return new LinuxTextInsertionSupport(LinuxTextInsertionBackend.X11ClipboardAndXTest, "X11 clipboard and synthetic paste tools are available.");
            }

            return new LinuxTextInsertionSupport(
                LinuxTextInsertionBackend.ManualPasteOnly,
                "X11 automatic paste requires xclip and xdotool.",
                "Install xclip and xdotool, or paste manually from the recovery clipboard copy.");
        }

        return new LinuxTextInsertionSupport(
            LinuxTextInsertionBackend.ManualPasteOnly,
            "Desktop session type is unknown; automatic text insertion is disabled.",
            "Start WaiComputer inside a Wayland or X11 graphical session.");
    }
}
