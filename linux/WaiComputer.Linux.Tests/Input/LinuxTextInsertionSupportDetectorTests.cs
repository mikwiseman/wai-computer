using FluentAssertions;
using WaiComputer.Linux.Input;
using WaiComputer.Linux.Platform;
using WaiComputer.Linux.Tests.TestDoubles;

namespace WaiComputer.Linux.Tests.Input;

public sealed class LinuxTextInsertionSupportDetectorTests
{
    [Fact]
    public async Task Wayland_requires_remote_desktop_and_clipboard_portals()
    {
        var env = LinuxDesktopEnvironment.From(new Dictionary<string, string?>
        {
            ["XDG_SESSION_TYPE"] = "wayland",
            ["WAYLAND_DISPLAY"] = "wayland-0",
            ["HOME"] = "/home/mik",
        });

        var support = await LinuxTextInsertionSupportDetector.DetectAsync(
            env,
            new PortalCapabilities(true, true, false, true),
            new ToolProbe(new FakeCommandRunner()));

        support.Backend.Should().Be(LinuxTextInsertionBackend.ManualPasteOnly);
        support.RecoveryAction.Should().Contain("portal");
    }

    [Fact]
    public async Task X11_requires_clipboard_and_synthetic_key_tools()
    {
        var commands = new FakeCommandRunner();
        commands.Enqueue("which", ["xclip"], new CommandResult(0, "/usr/bin/xclip\n", ""));
        commands.Enqueue("which", ["xdotool"], new CommandResult(1, "", ""));
        var env = LinuxDesktopEnvironment.From(new Dictionary<string, string?>
        {
            ["XDG_SESSION_TYPE"] = "x11",
            ["DISPLAY"] = ":0",
            ["HOME"] = "/home/mik",
        });

        var support = await LinuxTextInsertionSupportDetector.DetectAsync(
            env,
            new PortalCapabilities(false, false, false, false),
            new ToolProbe(commands));

        support.Backend.Should().Be(LinuxTextInsertionBackend.ManualPasteOnly);
        support.Detail.Should().Contain("xclip and xdotool");
    }
}
