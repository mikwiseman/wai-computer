namespace WaiComputer.Core.Dictation;

/// <summary>Thrown when text insertion into the focused app fails (drives the clipboard-fallback notice).</summary>
public sealed class TextInsertionException : Exception
{
    public TextInsertionException(string message, Exception? inner = null) : base(message, inner) { }
}

/// <summary>
/// Inserts dictated text into the focused application. Platforms implement:
/// Windows = clipboard + SendInput Ctrl+V; Linux = portals / XTest. Throws
/// <see cref="TextInsertionException"/> on failure so the orchestrator can run
/// the clipboard-recovery path (no silent failure).
/// </summary>
public interface ITextInserter
{
    /// <summary>Whether the platform can paste automatically vs. only place text on the clipboard.</summary>
    bool SupportsAutomaticPaste { get; }

    /// <summary>Whether the OS permission required to insert is currently granted.</summary>
    bool HasInsertPermission { get; }

    Task InsertAsync(string text, CancellationToken ct);
}
