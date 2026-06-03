namespace WaiComputer.Linux.Platform;

public sealed record PortalCapabilities(
    bool DesktopPortalAvailable,
    bool GlobalShortcutsAvailable,
    bool RemoteDesktopAvailable,
    bool ClipboardAvailable);

public sealed class PortalCapabilityProbe
{
    private const string DesktopPortalName = "org.freedesktop.portal.Desktop";
    private readonly ICommandRunner _commands;

    public PortalCapabilityProbe(ICommandRunner commands)
    {
        _commands = commands;
    }

    public async Task<PortalCapabilities> ProbeAsync(CancellationToken ct = default)
    {
        var names = await ListUserBusNamesAsync(ct).ConfigureAwait(false);
        if (!names.Contains(DesktopPortalName))
        {
            return new PortalCapabilities(false, false, false, false);
        }

        var globalShortcuts = await InterfaceExistsAsync("org.freedesktop.portal.GlobalShortcuts", ct).ConfigureAwait(false);
        var remoteDesktop = await InterfaceExistsAsync("org.freedesktop.portal.RemoteDesktop", ct).ConfigureAwait(false);
        var clipboard = await InterfaceExistsAsync("org.freedesktop.portal.Clipboard", ct).ConfigureAwait(false);
        return new PortalCapabilities(true, globalShortcuts, remoteDesktop, clipboard);
    }

    private async Task<HashSet<string>> ListUserBusNamesAsync(CancellationToken ct)
    {
        CommandResult result;
        try
        {
            result = await _commands.RunAsync("busctl", ["--user", "list", "--no-legend"], ct: ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch
        {
            return new HashSet<string>(StringComparer.Ordinal);
        }
        if (!result.Succeeded)
        {
            return new HashSet<string>(StringComparer.Ordinal);
        }

        var names = result.Stdout
            .Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(line => line.Split(' ', StringSplitOptions.RemoveEmptyEntries).FirstOrDefault())
            .Where(name => !string.IsNullOrWhiteSpace(name))
            .Select(name => name!);

        return new HashSet<string>(names, StringComparer.Ordinal);
    }

    private async Task<bool> InterfaceExistsAsync(string interfaceName, CancellationToken ct)
    {
        CommandResult result;
        try
        {
            result = await _commands.RunAsync(
                "busctl",
                ["--user", "introspect", DesktopPortalName, "/org/freedesktop/portal/desktop", interfaceName],
                ct: ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch
        {
            return false;
        }

        return result.Succeeded;
    }
}
