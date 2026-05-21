using WaiComputer.Linux.Platform;

namespace WaiComputer.Linux.Input;

public sealed record LinuxTextInsertionResult(bool Success, string? UserMessage = null)
{
    public static LinuxTextInsertionResult Ok() => new(true);
    public static LinuxTextInsertionResult ManualPaste() => new(false, "Text is on your clipboard - press Ctrl+V to paste manually.");
}

public sealed class LinuxTextInsertionService
{
    private readonly ICommandRunner _commands;
    private readonly LinuxTextInsertionSupport _support;

    public LinuxTextInsertionService(ICommandRunner commands, LinuxTextInsertionSupport support)
    {
        _commands = commands;
        _support = support;
    }

    public async Task<LinuxTextInsertionResult> InsertAsync(string text, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(text))
        {
            return new LinuxTextInsertionResult(false, "Nothing to insert.");
        }

        return _support.Backend switch
        {
            LinuxTextInsertionBackend.X11ClipboardAndXTest => await InsertX11Async(text, ct).ConfigureAwait(false),
            LinuxTextInsertionBackend.WaylandPortals => LinuxTextInsertionResult.ManualPaste(),
            _ => await CopyRecoveryOnlyAsync(text, ct).ConfigureAwait(false),
        };
    }

    private async Task<LinuxTextInsertionResult> InsertX11Async(string text, CancellationToken ct)
    {
        var copy = await TryRunAsync("xclip", ["-selection", "clipboard"], text, ct).ConfigureAwait(false);
        if (!copy.Succeeded)
        {
            return new LinuxTextInsertionResult(false, "Failed to copy text to clipboard.");
        }

        var paste = await TryRunAsync("xdotool", ["key", "ctrl+v"], null, ct).ConfigureAwait(false);
        return paste.Succeeded ? LinuxTextInsertionResult.Ok() : LinuxTextInsertionResult.ManualPaste();
    }

    private async Task<LinuxTextInsertionResult> CopyRecoveryOnlyAsync(string text, CancellationToken ct)
    {
        var wlCopy = await TryRunAsync("wl-copy", [], text, ct).ConfigureAwait(false);
        if (wlCopy.Succeeded)
        {
            return LinuxTextInsertionResult.ManualPaste();
        }

        var xclip = await TryRunAsync("xclip", ["-selection", "clipboard"], text, ct).ConfigureAwait(false);
        return xclip.Succeeded
            ? LinuxTextInsertionResult.ManualPaste()
            : new LinuxTextInsertionResult(false, "Failed to copy text to clipboard.");
    }

    private async Task<CommandResult> TryRunAsync(string fileName, IReadOnlyList<string> arguments, string? stdin, CancellationToken ct)
    {
        try
        {
            return await _commands.RunAsync(fileName, arguments, stdin, ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            return new CommandResult(127, "", ex.Message);
        }
    }
}
