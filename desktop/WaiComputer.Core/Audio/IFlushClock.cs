using System.Runtime.CompilerServices;

namespace WaiComputer.Core.Audio;

/// <summary>
/// Drives <see cref="DualAudioCapture"/>'s flush cadence. The production clock
/// ticks on a <see cref="PeriodicTimer"/>; tests substitute a manual clock so
/// flushing is deterministic.
/// </summary>
public interface IFlushClock
{
    IAsyncEnumerable<DateTimeOffset> Ticks(CancellationToken ct);
}

/// <summary>Ticks on a fixed interval (default 160 ms, matching the Mac flush cadence).</summary>
public sealed class PeriodicFlushClock : IFlushClock
{
    private readonly TimeSpan _interval;

    public PeriodicFlushClock(TimeSpan? interval = null)
        => _interval = interval ?? TimeSpan.FromMilliseconds(160);

    public async IAsyncEnumerable<DateTimeOffset> Ticks([EnumeratorCancellation] CancellationToken ct)
    {
        using var timer = new PeriodicTimer(_interval);
        while (await timer.WaitForNextTickAsync(ct).ConfigureAwait(false))
        {
            yield return DateTimeOffset.UtcNow;
        }
    }
}
