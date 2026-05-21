using FluentAssertions;
using WaiComputer.Linux.Hotkey;
using WaiComputer.Linux.Platform;

namespace WaiComputer.Linux.Tests.Hotkey;

public sealed class LinuxHotkeySupportDetectorTests
{
    [Fact]
    public void Wayland_requires_global_shortcuts_portal()
    {
        var env = LinuxDesktopEnvironment.From(new Dictionary<string, string?>
        {
            ["XDG_SESSION_TYPE"] = "wayland",
            ["WAYLAND_DISPLAY"] = "wayland-0",
            ["HOME"] = "/home/mik",
        });

        var support = LinuxHotkeySupportDetector.Detect(env, new PortalCapabilities(true, false, true, true));

        support.Backend.Should().Be(LinuxHotkeyBackend.Unsupported);
        support.RecoveryAction.Should().Contain("GNOME/KDE");
    }

    [Fact]
    public void X11_uses_grab_key_backend()
    {
        var env = LinuxDesktopEnvironment.From(new Dictionary<string, string?>
        {
            ["XDG_SESSION_TYPE"] = "x11",
            ["DISPLAY"] = ":0",
            ["HOME"] = "/home/mik",
        });

        var support = LinuxHotkeySupportDetector.Detect(env, new PortalCapabilities(false, false, false, false));

        support.Backend.Should().Be(LinuxHotkeyBackend.X11GrabKey);
    }
}
