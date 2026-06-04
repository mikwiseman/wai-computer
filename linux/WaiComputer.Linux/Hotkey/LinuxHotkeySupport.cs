using WaiComputer.Linux.Platform;

namespace WaiComputer.Linux.Hotkey;

public enum LinuxHotkeyBackend
{
    WaylandGlobalShortcutsPortal,
    X11GrabKey,
    Unsupported,
}

public sealed record LinuxHotkeySupport(
    LinuxHotkeyBackend Backend,
    string Detail,
    string? RecoveryAction = null)
{
    public bool IsSupported => Backend != LinuxHotkeyBackend.Unsupported;

    public CapabilityStatus ToCapabilityStatus() => IsSupported
        ? new CapabilityStatus("Global hotkey", LinuxCapabilityState.Supported, Detail)
        : new CapabilityStatus("Global hotkey", LinuxCapabilityState.Unsupported, Detail, RecoveryAction);
}

public static class LinuxHotkeySupportDetector
{
    public static LinuxHotkeySupport Detect(LinuxDesktopEnvironment environment, PortalCapabilities portals)
    {
        if (environment.IsWayland)
        {
            return portals.GlobalShortcutsAvailable
                ? new LinuxHotkeySupport(LinuxHotkeyBackend.WaylandGlobalShortcutsPortal, "Wayland global shortcuts portal is available.")
                : new LinuxHotkeySupport(
                    LinuxHotkeyBackend.Unsupported,
                    "Wayland session does not expose org.freedesktop.portal.GlobalShortcuts.",
                    "Use GNOME/KDE with xdg-desktop-portal support, or run an X11 session for XGrabKey.");
        }

        if (environment.IsX11)
        {
            return new LinuxHotkeySupport(LinuxHotkeyBackend.X11GrabKey, "X11 session can use XGrabKey.");
        }

        return new LinuxHotkeySupport(
            LinuxHotkeyBackend.Unsupported,
            "Desktop session type is unknown; global dictation hotkeys are disabled.",
            "Set XDG_SESSION_TYPE to wayland or x11 and start WaiComputer inside the graphical session.");
    }
}

public interface ILinuxHotkeyService : IDisposable
{
    LinuxHotkeyBackend Backend { get; }
    event Action? PushToTalkStart;
    event Action? PushToTalkStop;
    Task StartAsync(CancellationToken ct = default);
    Task StopAsync(CancellationToken ct = default);
}

public sealed class UnsupportedLinuxHotkeyService : ILinuxHotkeyService
{
    private readonly string _message;

    public UnsupportedLinuxHotkeyService(string message)
    {
        _message = message;
    }

    public LinuxHotkeyBackend Backend => LinuxHotkeyBackend.Unsupported;
    public event Action? PushToTalkStart;
    public event Action? PushToTalkStop;

    public Task StartAsync(CancellationToken ct = default)
    {
        _ = PushToTalkStart;
        _ = PushToTalkStop;
        throw new NotSupportedException(_message);
    }

    public Task StopAsync(CancellationToken ct = default) => Task.CompletedTask;
    public void Dispose()
    {
    }
}
