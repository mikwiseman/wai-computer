namespace WaiComputer.Core.Realtime;

/// <summary>
/// Pure policy deciding how long the close path should keep waiting for trailing
/// transcript frames before sending CloseStream, ported verbatim from the macOS
/// <c>RealtimeCloseDrainPolicy</c>. All instants are monotonic
/// <see cref="TimeSpan"/> offsets from a common origin (e.g. a Stopwatch), so the
/// policy is fully deterministic under test.
/// </summary>
public static class RealtimeCloseDrainPolicy
{
    /// <summary>Always wait at least this long after the drain starts.</summary>
    public static readonly TimeSpan MinimumWait = TimeSpan.FromMilliseconds(650);

    /// <summary>Upper bound to wait when no transcript has arrived at all.</summary>
    public static readonly TimeSpan NoTranscriptWait = TimeSpan.FromMilliseconds(2500);

    /// <summary>Silence after the last transcript that counts as "drained".</summary>
    public static readonly TimeSpan QuietWindow = TimeSpan.FromMilliseconds(900);

    /// <summary>
    /// Whether the drain loop should keep waiting.
    /// </summary>
    /// <param name="now">Current monotonic time.</param>
    /// <param name="deadline">Hard cutoff (drain start + caller timeout).</param>
    /// <param name="startedAt">When the drain began.</param>
    /// <param name="lastTranscriptEventAt">When the last transcript arrived, or null if none yet.</param>
    /// <param name="finalizationMarkerReceived">Whether the provider acknowledged finalize.</param>
    public static bool ShouldKeepWaiting(
        TimeSpan now,
        TimeSpan deadline,
        TimeSpan startedAt,
        TimeSpan? lastTranscriptEventAt,
        bool finalizationMarkerReceived)
    {
        if (now >= deadline)
        {
            return false;
        }

        var minimumWaitUntil = startedAt + MinimumWait;

        if (finalizationMarkerReceived && now >= minimumWaitUntil)
        {
            return false;
        }

        if (lastTranscriptEventAt is { } last)
        {
            var quietElapsed = (now - last) >= QuietWindow;
            return !(now >= minimumWaitUntil && quietElapsed);
        }

        return now < startedAt + NoTranscriptWait;
    }
}
