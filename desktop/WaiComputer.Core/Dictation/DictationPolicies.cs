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
