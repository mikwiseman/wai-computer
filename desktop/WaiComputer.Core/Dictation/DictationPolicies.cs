namespace WaiComputer.Core.Dictation;

/// <summary>Dictation session state at the moment push-to-talk is released.</summary>
public enum PushToTalkStopState
{
    Idle,
    Connecting,
    Listening,
    Finalizing,
}

/// <summary>What releasing push-to-talk should do for the current state.</summary>
public enum PushToTalkStopResolution
{
    /// <summary>Hands-free is active, or a finalize is already in progress.</summary>
    DoNothing,

    /// <summary>Provider is live — finalize now.</summary>
    FinishNow,

    /// <summary>Start path hasn't reached listening yet — defer so it fires once ready.</summary>
    DeferUntilReady,
}

/// <summary>
/// Pure policy porting the macOS <c>PushToTalkStopPolicy</c>
/// (GlobalHotkeyManager.swift): hands-free or an in-progress finalize does
/// nothing; a live (listening) session finalizes immediately; a start path that
/// hasn't reached listening yet (idle/connecting) defers the stop so it fires
/// the moment the session becomes ready (prevents the "starts then immediately
/// stops" race when the release arrives mid-handshake).
/// </summary>
public static class PushToTalkStopPolicy
{
    public static PushToTalkStopResolution Resolve(PushToTalkStopState state, bool isHandsFree)
    {
        if (isHandsFree)
        {
            return PushToTalkStopResolution.DoNothing;
        }

        return state switch
        {
            PushToTalkStopState.Listening => PushToTalkStopResolution.FinishNow,
            PushToTalkStopState.Idle or PushToTalkStopState.Connecting => PushToTalkStopResolution.DeferUntilReady,
            PushToTalkStopState.Finalizing => PushToTalkStopResolution.DoNothing,
            _ => PushToTalkStopResolution.DoNothing,
        };
    }
}

/// <summary>What a deferred stop should do once the session reaches listening.</summary>
public enum DeferredStopAction
{
    ContinueListening,
    FinishAfterReady,
}

/// <summary>
/// When a push-to-talk release arrived before the session was ready, this
/// decides what happens the moment it becomes ready: finish (unless hands-free,
/// where the release is ignored) or keep listening.
/// </summary>
public static class DeferredDictationStopPolicy
{
    public static DeferredStopAction Action(bool deferredStop, bool isHandsFree)
        => deferredStop && !isHandsFree ? DeferredStopAction.FinishAfterReady : DeferredStopAction.ContinueListening;
}

/// <summary>Timing for finalizing a dictation turn (porting the macOS DictationFinalizationPolicy).</summary>
public static class DictationFinalizationPolicy
{
    /// <summary>How long to keep capturing after the user stops, so the tail of the last word lands.</summary>
    public static readonly TimeSpan CaptureTailDelay = TimeSpan.FromMilliseconds(450);
}

/// <summary>Thrown when AI cleanup is enabled but fails or returns nothing (no silent fallback to raw).</summary>
public sealed class DictationCleanupException : Exception
{
    public DictationCleanupException(string message) : base(message) { }
}

/// <summary>
/// Decides the text to actually insert. With the post-filter off, the raw
/// transcript is used verbatim. With it on, the cleaned result is required — a
/// cleanup error or an empty result throws rather than silently inserting raw
/// (no-fallback: the user opted into cleanup, so a failure must surface).
/// </summary>
public static class DictationCleanupPolicy
{
    public static string TextToInsert(bool postFilterEnabled, string raw, string? cleanupResult, bool cleanupFailed)
    {
        if (!postFilterEnabled)
        {
            return raw;
        }
        if (cleanupFailed)
        {
            throw new DictationCleanupException("Dictation cleanup failed.");
        }
        var trimmed = cleanupResult?.Trim() ?? string.Empty;
        if (trimmed.Length == 0)
        {
            throw new DictationCleanupException("Dictation cleanup returned no text.");
        }
        return trimmed;
    }
}
