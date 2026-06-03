namespace WaiComputer.Linux.Platform;

public sealed class ToolProbe
{
    private readonly ICommandRunner _commands;

    public ToolProbe(ICommandRunner commands)
    {
        _commands = commands;
    }

    public async Task<bool> ExistsAsync(string name, CancellationToken ct = default)
    {
        try
        {
            var result = await _commands.RunAsync("which", [name], ct: ct).ConfigureAwait(false);
            return result.Succeeded && !string.IsNullOrWhiteSpace(result.Stdout);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch
        {
            return false;
        }
    }
}
