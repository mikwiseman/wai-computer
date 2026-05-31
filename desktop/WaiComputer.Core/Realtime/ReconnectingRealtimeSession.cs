using System.Threading.Channels;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

/// <summary>Tuning for <see cref="ReconnectingRealtimeSession"/>.</summary>
public sealed record ReconnectOptions(
    int MaxAttempts = 10,
    int BaseDelayMs = 500,
    int MaxDelayMs = 30_000,
    int MaxBufferChunks = 300);

/// <summary>
/// An <see cref="IRealtimeTranscriptionSession"/> decorator that adds resilient
/// auto-reconnect, porting the macOS WebSocketManager recording path. On a
/// transient drop it emits <see cref="TranscriptionEvent.Reconnecting"/>, waits a
/// bounded exponential backoff with jitter, re-mints the session config, opens a
/// fresh inner session, replays audio buffered during the gap (drop-oldest past
/// <see cref="ReconnectOptions.MaxBufferChunks"/>), and emits
/// <see cref="TranscriptionEvent.Reconnected"/>. After
/// <see cref="ReconnectOptions.MaxAttempts"/> failures it emits
/// <see cref="TranscriptionEvent.ReconnectionFailed"/> and stops. Collected
/// final segments survive reconnects. A fatal provider warning
/// (<see cref="TranscriptionErrorCodes.Fatal"/>) and an explicit EndTurn/Close
/// disable reconnect (no-fallback — surface and stop).
/// </summary>
public sealed class ReconnectingRealtimeSession : IRealtimeTranscriptionSession
{
    private readonly RealtimeTranscriptionSessionConfig _initialConfig;
    private readonly Func<RealtimeTranscriptionSessionConfig, IRealtimeTranscriptionSession> _sessionFactory;
    private readonly Func<CancellationToken, Task<RealtimeTranscriptionSessionConfig>> _remintAsync;
    private readonly ReconnectOptions _options;
    private readonly PcmRechunker _rechunker;

    private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>(
        new UnboundedChannelOptions { SingleReader = true });
    private readonly List<LiveTranscriptSegment> _allSegments = new();
    private readonly HashSet<string> _segmentKeys = new(StringComparer.Ordinal);
    private readonly Queue<byte[]> _buffer = new();
    private readonly object _gate = new();

    private IRealtimeTranscriptionSession? _inner;
    private Task? _supervisor;
    private CancellationTokenSource? _cts;
    private bool _reconnectEnabled;
    private bool _reconnecting;
    private bool _closed;
    private bool _firstConnectForwarded;
    private Exception? _lastError;

    public ReconnectingRealtimeSession(
        RealtimeTranscriptionSessionConfig initialConfig,
        Func<RealtimeTranscriptionSessionConfig, IRealtimeTranscriptionSession> sessionFactory,
        Func<CancellationToken, Task<RealtimeTranscriptionSessionConfig>> remintAsync,
        ReconnectOptions? options = null)
    {
        _initialConfig = initialConfig;
        _sessionFactory = sessionFactory;
        _remintAsync = remintAsync;
        _options = options ?? new ReconnectOptions();
        _rechunker = new PcmRechunker(initialConfig.SampleRate, initialConfig.Channels);
    }

    public RealtimeProvider Provider => _initialConfig.Provider;

    public IAsyncEnumerable<TranscriptionEvent> Events => _events.Reader.ReadAllAsync();

    public IReadOnlyList<LiveTranscriptSegment> CollectedSegments
    {
        get { lock (_gate) { return _allSegments.ToArray(); } }
    }

    public async Task OpenAsync(CancellationToken ct)
    {
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var inner = _sessionFactory(_initialConfig);
        // Initial open is NOT retried — a first-connect failure is surfaced (Mac
        // only enables reconnect after the first success).
        await inner.OpenAsync(_cts.Token).ConfigureAwait(false);
        lock (_gate) { _inner = inner; _reconnectEnabled = true; }
        _supervisor = Task.Run(() => SuperviseAsync(_cts.Token));
    }

    public async Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct)
    {
        var chunks = _rechunker.Push(pcm16Mono.Span, forceFlush: false);
        foreach (var chunk in chunks)
        {
            IRealtimeTranscriptionSession? inner;
            bool buffered;
            lock (_gate)
            {
                inner = _inner;
                buffered = _reconnecting || _closed || inner is null;
                if (buffered)
                {
                    Enqueue(chunk);
                }
            }

            if (buffered)
            {
                continue;
            }

            try
            {
                await inner!.SendPcmAsync(chunk, ct).ConfigureAwait(false);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                // Don't interrupt capture — buffer the chunk; the inner socket
                // fault will surface as a drop in the pump and drive reconnect.
                lock (_gate) { Enqueue(chunk); _lastError = ex; }
            }
        }
    }

    public async Task EndTurnAsync()
    {
        var tail = _rechunker.Push(ReadOnlySpan<byte>.Empty, forceFlush: true);
        IRealtimeTranscriptionSession? inner;
        lock (_gate) { _reconnectEnabled = false; inner = _inner; }
        if (inner is null)
        {
            return;
        }
        foreach (var chunk in tail)
        {
            await inner.SendPcmAsync(chunk, CancellationToken.None).ConfigureAwait(false);
        }
        await inner.EndTurnAsync().ConfigureAwait(false);
    }

    public async Task CloseAsync(TimeSpan timeout)
    {
        IRealtimeTranscriptionSession? inner;
        lock (_gate) { _closed = true; _reconnectEnabled = false; inner = _inner; }
        _cts?.Cancel();
        if (inner is not null)
        {
            try { await inner.CloseAsync(timeout).ConfigureAwait(false); } catch { /* closing */ }
        }
        if (_supervisor is { } supervisor)
        {
            try { await supervisor.ConfigureAwait(false); } catch { /* cancelled */ }
        }
        _events.Writer.TryComplete();
    }

    public async ValueTask DisposeAsync()
    {
        try { await CloseAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false); } catch { /* ignore */ }
    }

    /// <summary>Exponential backoff base (ms), capped at <c>MaxDelayMs</c>. Jitter is added by the caller.</summary>
    internal static long BaseBackoffMs(int attempt, ReconnectOptions options)
    {
        var shift = Math.Min(attempt - 1, 30);
        var raw = (long)options.BaseDelayMs * (1L << shift);
        return Math.Min(raw, options.MaxDelayMs);
    }

    private async Task SuperviseAsync(CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested)
            {
                var inner = CurrentInner();
                if (inner is null)
                {
                    break;
                }

                var ended = await PumpAsync(inner, ct).ConfigureAwait(false);
                if (ended is PumpEnd.RequestedClose or PumpEnd.FatalProviderError || ct.IsCancellationRequested)
                {
                    break;
                }
                if (!ReconnectEnabled())
                {
                    break;
                }
                if (!await ReconnectAsync(ct).ConfigureAwait(false))
                {
                    break;
                }
            }
        }
        catch (OperationCanceledException) { /* normal shutdown */ }
        finally
        {
            _events.Writer.TryComplete();
        }
    }

    private async Task<PumpEnd> PumpAsync(IRealtimeTranscriptionSession inner, CancellationToken ct)
    {
        await foreach (var ev in inner.Events.WithCancellation(ct).ConfigureAwait(false))
        {
            switch (ev)
            {
                case TranscriptionEvent.Transcript transcript:
                    RecordSegment(transcript.Segment);
                    await _events.Writer.WriteAsync(ev, ct).ConfigureAwait(false);
                    break;

                case TranscriptionEvent.Connected:
                    if (!_firstConnectForwarded)
                    {
                        _firstConnectForwarded = true;
                        await _events.Writer.WriteAsync(ev, ct).ConfigureAwait(false);
                    }
                    break;

                case TranscriptionEvent.ProviderWarning warning:
                    await _events.Writer.WriteAsync(ev, ct).ConfigureAwait(false);
                    if (TranscriptionErrorCodes.Fatal.Contains(warning.Code))
                    {
                        return PumpEnd.FatalProviderError;
                    }
                    break;

                case TranscriptionEvent.Disconnected:
                    return ReconnectEnabled() ? PumpEnd.Dropped : PumpEnd.RequestedClose;

                default:
                    await _events.Writer.WriteAsync(ev, ct).ConfigureAwait(false);
                    break;
            }
        }

        // Inner event stream completed without an explicit Disconnected.
        return ReconnectEnabled() ? PumpEnd.Dropped : PumpEnd.RequestedClose;
    }

    private async Task<bool> ReconnectAsync(CancellationToken ct)
    {
        lock (_gate) { _reconnecting = true; }
        try
        {
            for (var attempt = 1; attempt <= _options.MaxAttempts; attempt++)
            {
                await _events.Writer.WriteAsync(new TranscriptionEvent.Reconnecting(attempt, _options.MaxAttempts), ct).ConfigureAwait(false);

                var baseMs = BaseBackoffMs(attempt, _options);
                var jitter = baseMs > 0 ? Random.Shared.NextInt64(0, baseMs / 2 + 1) : 0;
                var delay = baseMs + jitter;
                if (delay > 0)
                {
                    await Task.Delay(TimeSpan.FromMilliseconds(delay), ct).ConfigureAwait(false);
                }

                try
                {
                    var cfg = await _remintAsync(ct).ConfigureAwait(false);
                    var next = _sessionFactory(cfg);
                    await next.OpenAsync(ct).ConfigureAwait(false);

                    IRealtimeTranscriptionSession? old;
                    List<byte[]> replay;
                    lock (_gate)
                    {
                        old = _inner;
                        _inner = next;
                        _reconnecting = false;
                        replay = new List<byte[]>(_buffer);
                        _buffer.Clear();
                    }

                    MergeSegments(next.CollectedSegments);
                    if (old is not null)
                    {
                        try { await old.DisposeAsync().ConfigureAwait(false); } catch { /* old session */ }
                    }
                    foreach (var chunk in replay)
                    {
                        await next.SendPcmAsync(chunk, ct).ConfigureAwait(false);
                    }

                    await _events.Writer.WriteAsync(new TranscriptionEvent.Reconnected(), ct).ConfigureAwait(false);
                    return true;
                }
                catch (OperationCanceledException)
                {
                    throw;
                }
                catch (Exception ex)
                {
                    _lastError = ex;
                    lock (_gate) { _reconnecting = true; } // still reconnecting; try next attempt
                }
            }

            await _events.Writer.WriteAsync(new TranscriptionEvent.ReconnectionFailed(_lastError), CancellationToken.None).ConfigureAwait(false);
            return false;
        }
        finally
        {
            lock (_gate) { _reconnecting = false; }
        }
    }

    private IRealtimeTranscriptionSession? CurrentInner()
    {
        lock (_gate) { return _inner; }
    }

    private bool ReconnectEnabled()
    {
        lock (_gate) { return _reconnectEnabled && !_closed; }
    }

    private void Enqueue(byte[] chunk)
    {
        _buffer.Enqueue(chunk);
        while (_buffer.Count > _options.MaxBufferChunks)
        {
            _buffer.Dequeue();
        }
    }

    private void RecordSegment(LiveTranscriptSegment segment)
    {
        if (!segment.IsFinal)
        {
            return;
        }
        lock (_gate)
        {
            var key = $"{segment.StartMs}:{segment.EndMs}:{segment.Text}";
            if (_segmentKeys.Add(key))
            {
                _allSegments.Add(segment);
            }
        }
    }

    private void MergeSegments(IReadOnlyList<LiveTranscriptSegment> segments)
    {
        lock (_gate)
        {
            foreach (var segment in segments)
            {
                if (!segment.IsFinal)
                {
                    continue;
                }
                var key = $"{segment.StartMs}:{segment.EndMs}:{segment.Text}";
                if (_segmentKeys.Add(key))
                {
                    _allSegments.Add(segment);
                }
            }
        }
    }

    private enum PumpEnd
    {
        Dropped,
        RequestedClose,
        FatalProviderError,
    }
}
