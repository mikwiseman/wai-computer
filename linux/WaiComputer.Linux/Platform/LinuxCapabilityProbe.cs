using WaiComputer.Linux.Audio;
using WaiComputer.Linux.Hotkey;
using WaiComputer.Linux.Input;

namespace WaiComputer.Linux.Platform;

public sealed class LinuxCapabilityProbe
{
    private readonly PulseAudioDeviceProbe _audio;
    private readonly PortalCapabilityProbe _portal;
    private readonly ToolProbe _tools;
    private readonly Func<LinuxDesktopEnvironment> _environment;

    public LinuxCapabilityProbe(
        PulseAudioDeviceProbe audio,
        PortalCapabilityProbe portal,
        ToolProbe tools,
        Func<LinuxDesktopEnvironment>? environment = null)
    {
        _audio = audio;
        _portal = portal;
        _tools = tools;
        _environment = environment ?? LinuxDesktopEnvironment.FromCurrentProcess;
    }

    public async Task<LinuxCapabilityReport> ProbeAsync(CancellationToken ct = default)
    {
        var env = _environment();
        var portals = await _portal.ProbeAsync(ct).ConfigureAwait(false);
        var sources = await _audio.ProbeAsync(ct).ConfigureAwait(false);
        var hotkey = LinuxHotkeySupportDetector.Detect(env, portals);
        var text = await LinuxTextInsertionSupportDetector.DetectAsync(env, portals, _tools, ct).ConfigureAwait(false);
        var secretTool = await _tools.ExistsAsync("secret-tool", ct).ConfigureAwait(false);

        return new LinuxCapabilityReport(
            sources.DefaultMicrophone is not null
                ? new CapabilityStatus("Microphone audio", LinuxCapabilityState.Supported, sources.DefaultMicrophone.Name)
                : new CapabilityStatus("Microphone audio", LinuxCapabilityState.Unsupported, "No PulseAudio/PipeWire microphone source was exposed.", "Connect a microphone and confirm `pactl list short sources` shows a non-monitor source."),
            sources.DefaultSystemMonitor is not null
                ? new CapabilityStatus("System audio", LinuxCapabilityState.Supported, sources.DefaultSystemMonitor.Name)
                : new CapabilityStatus("System audio", LinuxCapabilityState.Unsupported, "No PulseAudio/PipeWire monitor source was exposed for the active sink.", "Enable a PipeWire/PulseAudio session with monitor sources; v1 does not install drivers or loopback helpers."),
            hotkey.ToCapabilityStatus(),
            text.ToCapabilityStatus(),
            secretTool
                ? new CapabilityStatus("Session storage", LinuxCapabilityState.Supported, "Secret Service is reachable through secret-tool.")
                : new CapabilityStatus("Session storage", LinuxCapabilityState.Unsupported, "Secret Service CLI is unavailable.", "Install libsecret tools and unlock a Secret Service keyring."),
            new CapabilityStatus("Desktop integration", LinuxCapabilityState.Supported, "Uses XDG .desktop, x-scheme-handler/waicomputer, notifications, and StatusNotifier/AppIndicator when the shell supports them."));
    }
}
