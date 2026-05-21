using FluentAssertions;
using WaiComputer.Linux.Audio;
using WaiComputer.Linux.Platform;
using WaiComputer.Linux.Tests.TestDoubles;

namespace WaiComputer.Linux.Tests.Platform;

public sealed class LinuxCapabilityProbeTests
{
    [Fact]
    public async Task Reports_missing_system_monitor_as_unsupported_not_mic_only_success()
    {
        var commands = new FakeCommandRunner();
        commands.Enqueue("busctl", ["--user", "list", "--no-legend"], new CommandResult(0, "org.freedesktop.portal.Desktop 123 user\norg.freedesktop.secrets 124 user\n", ""));
        commands.Enqueue("busctl", ["--user", "introspect", "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.GlobalShortcuts"], new CommandResult(0, "", ""));
        commands.Enqueue("busctl", ["--user", "introspect", "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.RemoteDesktop"], new CommandResult(0, "", ""));
        commands.Enqueue("busctl", ["--user", "introspect", "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Clipboard"], new CommandResult(0, "", ""));
        commands.Enqueue("pactl", ["info"], new CommandResult(0, """
Default Sink: speaker
Default Source: mic
""", ""));
        commands.Enqueue("pactl", ["list", "short", "sources"], new CommandResult(0, """
1	mic	PipeWire	s16le 1ch 48000Hz	RUNNING
""", ""));
        commands.Enqueue("which", ["secret-tool"], new CommandResult(0, "/usr/bin/secret-tool\n", ""));

        var probe = new LinuxCapabilityProbe(
            new PulseAudioDeviceProbe(commands),
            new PortalCapabilityProbe(commands),
            new ToolProbe(commands),
            () => LinuxDesktopEnvironment.From(new Dictionary<string, string?>
            {
                ["XDG_SESSION_TYPE"] = "wayland",
                ["WAYLAND_DISPLAY"] = "wayland-0",
                ["HOME"] = "/home/mik",
            }));

        var report = await probe.ProbeAsync();

        report.MicrophoneAudio.State.Should().Be(LinuxCapabilityState.Supported);
        report.SystemAudio.State.Should().Be(LinuxCapabilityState.Unsupported);
        report.SystemAudio.Detail.Should().Contain("monitor source");
    }
}
