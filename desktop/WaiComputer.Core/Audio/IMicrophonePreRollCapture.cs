using System.Threading.Channels;

namespace WaiComputer.Core.Audio;

/// <summary>A leased dictation audio stream: the captured pre-roll plus the live frame feed.</summary>
public sealed class DictationAudioLease
{
    public DictationAudioLease(IReadOnlyList<AudioFrame> preRoll, ChannelReader<AudioFrame> frames)
    {
        PreRoll = preRoll;
        Frames = frames;
    }

    /// <summary>Audio captured before the lease (up to ~500 ms) so the first word isn't clipped.</summary>
    public IReadOnlyList<AudioFrame> PreRoll { get; }

    /// <summary>Live frames captured after the lease.</summary>
    public ChannelReader<AudioFrame> Frames { get; }
}

/// <summary>
/// Microphone capture that keeps a rolling pre-roll buffer warm before dictation
/// starts (the .NET analogue of the macOS AudioEngineHost). Prewarm starts the
/// mic and buffers recent audio; <see cref="Lease"/> snapshots that pre-roll and
/// switches to streaming live frames.
/// </summary>
public interface IMicrophonePreRollCapture : IAsyncDisposable
{
    Task PrewarmAsync(CancellationToken ct);
    Task TeardownAsync();
    DictationAudioLease Lease();
}

/// <summary>
/// Portable <see cref="IMicrophonePreRollCapture"/> over any <see cref="IMicrophoneCapture"/>.
/// Before the lease, incoming frames accumulate in a <see cref="PcmRingBuffer"/>
/// (~500 ms); on lease the ring is snapshotted as the pre-roll and subsequent
/// frames are routed to a live channel. Testable with a fake mic.
/// </summary>
public sealed class PreRollMicrophoneCapture : IMicrophonePreRollCapture
{
    private readonly IMicrophoneCapture _inner;
    private readonly PcmRingBuffer _ring;
    private readonly object _gate = new();
    private Channel<AudioFrame>? _live;
    private Task? _pump;
    private CancellationTokenSource? _cts;
    private bool _started;

    public PreRollMicrophoneCapture(IMicrophoneCapture inner, AudioCaptureConfig config)
    {
        _inner = inner;
        _ring = new PcmRingBuffer(Math.Max(1, (int)(config.SampleRate * 0.5))); // 500 ms
    }

    public async Task PrewarmAsync(CancellationToken ct)
    {
        // Idempotent: a second prewarm before teardown must not orphan the cts/pump
        // or double-start the mic (the macOS AudioEngineHost guards prewarm the same way).
        lock (_gate) { if (_started) return; _started = true; }
        try
        {
            _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            await _inner.StartAsync(_cts.Token).ConfigureAwait(false);
            _pump = Task.Run(() => PumpAsync(_cts.Token));
        }
        catch
        {
            lock (_gate) { _started = false; }
            throw;
        }
    }

    private async Task PumpAsync(CancellationToken ct)
    {
        try
        {
            await foreach (var frame in _inner.Frames.ReadAllAsync(ct).ConfigureAwait(false))
            {
                Channel<AudioFrame>? live;
                lock (_gate)
                {
                    live = _live;
                    if (live is null)
                    {
                        _ring.Append(frame.Pcm16);
                    }
                }
                live?.Writer.TryWrite(frame);
            }
        }
        catch (OperationCanceledException) { /* stopping */ }
    }

    public DictationAudioLease Lease()
    {
        lock (_gate)
        {
            if (_live is not null)
            {
                throw new InvalidOperationException("Microphone is already leased.");
            }
            var snapshot = _ring.Snapshot();
            var preRoll = snapshot.Length > 0
                ? new[] { new AudioFrame(snapshot, TimeSpan.Zero, snapshot.Length / 2) }
                : Array.Empty<AudioFrame>();
            _live = Channel.CreateUnbounded<AudioFrame>(new UnboundedChannelOptions { SingleReader = true, SingleWriter = true });
            return new DictationAudioLease(preRoll, _live.Reader);
        }
    }

    public async Task TeardownAsync()
    {
        _cts?.Cancel();
        try { await _inner.StopAsync().ConfigureAwait(false); } catch { /* stopping */ }
        if (_pump is { } pump)
        {
            try { await pump.ConfigureAwait(false); } catch { /* cancelled */ }
        }
        // Reset to a fresh state so the capture is reusable for the next dictation turn:
        // complete + drop the live channel (else a re-Lease throws "already leased"), clear the
        // ring (else stale pre-roll from the prior turn leaks in), and re-arm prewarm.
        lock (_gate)
        {
            _live?.Writer.TryComplete();
            _live = null;
            _ring.Clear();
            _cts?.Dispose();
            _cts = null;
            _pump = null;
            _started = false;
        }
    }

    public async ValueTask DisposeAsync()
    {
        await TeardownAsync().ConfigureAwait(false);
        await _inner.DisposeAsync().ConfigureAwait(false);
    }
}
