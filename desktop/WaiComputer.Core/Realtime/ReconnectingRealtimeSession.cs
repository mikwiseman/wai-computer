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
/// <see cref="TranscriptionEvent.Reconnected"/>. The reconnect attempt budget is
/// cumulative across the session lifetime (matching Mac, and preventing infinite
/// flapping); after it is exhausted it emits
/// <see cref="TranscriptionEvent.ReconnectionFailed"/> and stops. Collected final
/// segments survive reconnects (deduped against the previous final, like Mac). A
/// fatal provider warning and an explicit EndTurn/Close disable reconnect
/// (no-fallback — surface and stop).
///
/// Threading: a single <see cref="SemaphoreSlim"/> serialises every operation that
/// touches the (single-producer) re-chunker or sends a frame — live sends, the
/// reconnect replay, and the end-turn flush — so frame ordering is total and the
/// re-chunker is never raced. A separate monitor guards fast state.
/// </summary>
public sealed class ReconnectingRealtimeSession : IRealtimeTranscriptionSession
{
    private readonly RealtimeTranscriptionSessionConfig _initialConfig;
    private readonly Func<RealtimeTranscriptionSessionConfig, IRealtimeTranscriptionSession> _sessionFactory;
    private readonly Func<CancellationToken, Task<RealtimeTranscriptionSessionConfig>> _remintAsync;
    private readonly ReconnectOptions _options;
    private readonly PcmRechunker _rechunker;

    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>(
        new UnboundedChannelOptions { SingleReader = true });
    private readonly List<LiveTranscriptSegment> _allSegments = new();
    private readonly Queue<byte[]> _buffer = new();
    private readonly object _gate = new();

    private IRealtimeTranscriptionSession? _inner;
    private Task? _supervisor;
    private CancellationTokenSource? _cts;
    private bool _reconnectEnabled;
    private bool _reconnecting;
    private bool _closed;
    private bool _pendingEndTurn;
    private bool _firstConnectForwarded;
    private int _reconnectAttempts;
    private string? _lastFinalNormalized;
    private Exception? _lastError;

    public ReconnectingRealtimeSession(
        RealtimeTranscriptionSessionConfig initialConfig,
        Func<RealtimeTranscriptionSessionConfig, IRealtimeTranscriptionSession> sessionFactory,
        Func<CancellationToken, Task<RealtimeTranscriptionSessionConfig>> remintAsync,
        ReconnectOptions? options = null)
    {
        _options = options ?? new ReconnectOptions();
        if (_options.MaxAttempts < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(options), _options.MaxAttempts, "MaxAttempts must be >= 1.");
        }
        if (_options.BaseDelayMs < 0 || _options.MaxDelayMs < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(options), "Backoff delays must be >= 0.");
        }
        if (_options.MaxBufferChunks < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(options), _options.MaxBufferChunks, "MaxBufferChunks must be >= 1.");
        }

        _initialConfig = initialConfig;
        _sessionFactory = sessionFactory;
        _remintAsync = remintAsync;
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
        try
        {
            // Initial open is NOT retried — a first-connect failure is surfaced
            // (Mac only enables reconnect after the first success).
            await inner.OpenAsync(_cts.Token).ConfigureAwait(false);
        }
        catch
        {
            try { await inner.DisposeAsync().ConfigureAwait(false); } catch { /* opening */ }
            _cts.Dispose();
            _cts = null;
            throw;
        }

        lock (_gate) { _inner = inner; _reconnectEnabled = true; }
        _supervisor = Task.Run(() => SuperviseAsync(_cts.Token));
    }

    public async Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct)
    {
        // The send lock serialises re-chunker access (single-producer) and frame
        // ordering against the reconnect replay loop and end-turn flush.
        await _sendLock.WaitAsync(ct).ConfigureAwait(false);
        try
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
                    // Don't interrupt capture — buffer the chunk; the faulted
                    // socket surfaces as a drop in the pump and drives reconnect.
                    lock (_gate) { Enqueue(chunk); _lastError = ex; }
                }
            }
        }
        finally
        {
            _sendLock.Release();
        }
    }

    public async Task EndTurnAsync()
    {
        await _sendLock.WaitAsync().ConfigureAwait(false);
        try
        {
            IRealtimeTranscriptionSession? inner;
            bool defer;
            lock (_gate)
            {
                _reconnectEnabled = false;
                inner = _inner;
                defer = _reconnecting || inner is null;
                if (defer)
                {
                    // Reconnect is in flight — finalize the *reconnected* socket
                    // once it is up (mirrors Mac deferring the commit).
                    _pendingEndTurn = true;
                }
            }

            if (defer)
            {
                return;
            }

            foreach (var chunk in _rechunker.Push(ReadOnlySpan<byte>.Empty, forceFlush: true))
            {
                await inner!.SendPcmAsync(chunk, CancellationToken.None).ConfigureAwait(false);
            }
            await inner!.EndTurnAsync().ConfigureAwait(false);
        }
        finally
        {
            _sendLock.Release();
        }
    }

    public async Task CloseAsync(TimeSpan timeout)
    {
        lock (_gate) { _closed = true; _reconnectEnabled = false; }
        _cts?.Cancel();

        if (_supervisor is { } supervisor)
        {
            try { await supervisor.WaitAsync(timeout).ConfigureAwait(false); }
            catch { /* timed out or cancelled — fall through to dispose */ }
        }

        // Re-read the current inner AFTER the supervisor has stopped so a session
        // swapped in by a racing reconnect is the one we tear down.
        IRealtimeTranscriptionSession? inner;
        lock (_gate) { inner = _inner; _inner = null; }
        if (inner is not null)
        {
            try { await inner.CloseAsync(timeout).ConfigureAwait(false); } catch { /* closing */ }
            try { await inner.DisposeAsync().ConfigureAwait(false); } catch { /* closing */ }
        }

        _cts?.Dispose();
        _cts = null;
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

                // Drop detected: enter the reconnecting state immediately so live
                // audio buffers (Mac sets isReconnecting + webSocket=nil at once),
                // and dispose the dead session before retrying.
                IRealtimeTranscriptionSession? dead;
                lock (_gate) { dead = _inner; _inner = null; _reconnecting = true; }
                if (dead is not null)
                {
                    try { await dead.DisposeAsync().ConfigureAwait(false); } catch { /* dead session */ }
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
            lock (_gate) { _reconnecting = false; }
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
                    if (RecordSegment(transcript.Segment))
                    {
                        await _events.Writer.WriteAsync(ev, ct).ConfigureAwait(false);
                    }
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
        while (true)
        {
            int attempt;
            lock (_gate)
            {
                if (_reconnectAttempts >= _options.MaxAttempts)
                {
                    break;
                }
                attempt = ++_reconnectAttempts; // cumulative across the session lifetime
            }

            await _events.Writer.WriteAsync(new TranscriptionEvent.Reconnecting(attempt, _options.MaxAttempts), ct).ConfigureAwait(false);

            var baseMs = BaseBackoffMs(attempt, _options);
            var jitter = baseMs > 0 ? Random.Shared.NextInt64(0, baseMs / 2 + 1) : 0;
            var delay = baseMs + jitter;
            if (delay > 0)
            {
                await Task.Delay(TimeSpan.FromMilliseconds(delay), ct).ConfigureAwait(false);
            }

            IRealtimeTranscriptionSession? next = null;
            var swapped = false;
            try
            {
                var cfg = await _remintAsync(ct).ConfigureAwait(false);
                next = _sessionFactory(cfg);
                await next.OpenAsync(ct).ConfigureAwait(false);

                // Hold the send lock across the swap + replay so no live frame can
                // interleave with the replayed buffer (total send ordering).
                await _sendLock.WaitAsync(ct).ConfigureAwait(false);
                try
                {
                    List<byte[]> replay;
                    bool doEndTurn;
                    lock (_gate)
                    {
                        _inner = next;
                        swapped = true;
                        replay = new List<byte[]>(_buffer);
                        _buffer.Clear();
                        doEndTurn = _pendingEndTurn;
                    }

                    foreach (var chunk in replay)
                    {
                        await next.SendPcmAsync(chunk, ct).ConfigureAwait(false);
                    }

                    if (doEndTurn)
                    {
                        foreach (var chunk in _rechunker.Push(ReadOnlySpan<byte>.Empty, forceFlush: true))
                        {
                            await next.SendPcmAsync(chunk, ct).ConfigureAwait(false);
                        }
                        await next.EndTurnAsync().ConfigureAwait(false);
                        lock (_gate) { _pendingEndTurn = false; }
                    }

                    // Only now do live sends bypass the buffer — after replay drained.
                    lock (_gate) { _reconnecting = false; }
                }
                finally
                {
                    _sendLock.Release();
                }

                await _events.Writer.WriteAsync(new TranscriptionEvent.Reconnected(), ct).ConfigureAwait(false);
                return true;
            }
            catch (OperationCanceledException)
            {
                if (next is not null && !swapped)
                {
                    try { await next.DisposeAsync().ConfigureAwait(false); } catch { /* aborted */ }
                }
                throw;
            }
            catch (Exception ex)
            {
                lock (_gate) { _lastError = ex; }
                if (next is not null && !swapped)
                {
                    try { await next.DisposeAsync().ConfigureAwait(false); } catch { /* failed attempt */ }
                }
            }
        }

        Exception? cause;
        lock (_gate) { cause = _lastError; }
        await _events.Writer.WriteAsync(
            new TranscriptionEvent.ReconnectionFailed(cause ?? new InvalidOperationException("Realtime reconnection attempts exhausted.")),
            CancellationToken.None).ConfigureAwait(false);
        return false;
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

    /// <summary>
    /// Records a final segment, deduping against only the previous final's
    /// whitespace-normalized text (Mac semantics). Returns false when the segment
    /// is a duplicate that should be suppressed (not stored, not emitted).
    /// Interim segments are always forwarded and never stored.
    /// </summary>
    private bool RecordSegment(LiveTranscriptSegment segment)
    {
        if (!segment.IsFinal)
        {
            return true;
        }

        var normalized = Normalize(segment.Text);
        lock (_gate)
        {
            if (normalized.Length > 0 && normalized == _lastFinalNormalized)
            {
                return false;
            }
            _lastFinalNormalized = normalized;
            _allSegments.Add(segment);
            return true;
        }
    }

    private static string Normalize(string text)
        => string.Join(' ', text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

    private enum PumpEnd
    {
        Dropped,
        RequestedClose,
        FatalProviderError,
    }
}
