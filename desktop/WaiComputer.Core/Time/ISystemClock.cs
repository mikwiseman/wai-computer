namespace WaiComputer.Core.Time;

/// <summary>
/// Abstracts wall-clock reads + delays so the recording duration timer, the
/// system-audio poll, and sync backoff are deterministically testable.
/// </summary>
public interface ISystemClock
{
    DateTimeOffset UtcNow { get; }
    Task Delay(TimeSpan duration, CancellationToken ct);
}

/// <summary>Production clock backed by the system time and <see cref="Task.Delay(TimeSpan, CancellationToken)"/>.</summary>
public sealed class RealSystemClock : ISystemClock
{
    public DateTimeOffset UtcNow => DateTimeOffset.UtcNow;

    public Task Delay(TimeSpan duration, CancellationToken ct) => Task.Delay(duration, ct);
}
