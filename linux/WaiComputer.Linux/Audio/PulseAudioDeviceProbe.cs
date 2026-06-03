using WaiComputer.Linux.Platform;

namespace WaiComputer.Linux.Audio;

public sealed class PulseAudioDeviceProbe
{
    private readonly ICommandRunner _commands;

    public PulseAudioDeviceProbe(ICommandRunner commands)
    {
        _commands = commands;
    }

    public async Task<PulseAudioSourceSnapshot> ProbeAsync(CancellationToken ct = default)
    {
        CommandResult info;
        try
        {
            info = await _commands.RunAsync("pactl", ["info"], ct: ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch
        {
            return new PulseAudioSourceSnapshot(null, null, []);
        }
        if (!info.Succeeded)
        {
            return new PulseAudioSourceSnapshot(null, null, []);
        }

        CommandResult sources;
        try
        {
            sources = await _commands.RunAsync("pactl", ["list", "short", "sources"], ct: ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch
        {
            return new PulseAudioSourceSnapshot(null, null, []);
        }
        if (!sources.Succeeded)
        {
            return new PulseAudioSourceSnapshot(null, null, []);
        }

        return PulseAudioSourceParser.Parse(info.Stdout, sources.Stdout);
    }
}
