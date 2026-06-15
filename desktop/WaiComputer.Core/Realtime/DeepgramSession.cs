using System.Diagnostics;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// Deepgram Nova-3 realtime transcription.
/// Auth: <c>Authorization: Bearer …</c>. Audio: binary linear16 PCM frames.
/// </summary>
public sealed class DeepgramSession : IRealtimeTranscriptionSession
{
    private readonly RealtimeTranscriptionSessionConfig _config;
    private readonly IWebSocketTransport _ws;
    private readonly List<LiveTranscriptSegment> _segments = new();
    private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>(
        new UnboundedChannelOptions { SingleReader = true });
    private readonly HashSet<string> _finalSegmentKeys = new(StringComparer.Ordinal);
    private readonly object _drainLock = new();
    private readonly Stopwatch _drainClock = new();

    private Task? _readLoop;
    private Task? _keepAliveLoop;
    private CancellationTokenSource? _cts;
    private bool _hasSentAudioSinceLastFinalize;
    private bool _endTurnSent;
    private bool _closeStreamSent;
    private TimeSpan? _lastTranscriptEventAt;
    private bool _finalizationMarkerReceived;
    private static readonly TimeSpan DrainPollInterval = TimeSpan.FromMilliseconds(50);
    private static readonly TimeSpan TransportCloseTimeout = TimeSpan.FromSeconds(1);

    public RealtimeProvider Provider => RealtimeProvider.Deepgram;
    public IAsyncEnumerable<TranscriptionEvent> Events => _events.Reader.ReadAllAsync();
    public IReadOnlyList<LiveTranscriptSegment> CollectedSegments => _segments;

    public DeepgramSession(RealtimeTranscriptionSessionConfig config, IWebSocketTransport? transport = null)
    {
        _config = config;
        _ws = transport ?? new ClientWebSocketTransport();
    }

    public async Task OpenAsync(CancellationToken ct)
    {
        ValidateConfig();
        ResetDrainState();
        var url = _config.WebSocketUrl!;
        await _ws.ConnectAsync(new Uri(url), options =>
        {
            options.SetRequestHeader("Authorization", $"Bearer {_config.Token}");
        }, ct).ConfigureAwait(false);

        await _events.Writer.WriteAsync(new TranscriptionEvent.Connected(), ct).ConfigureAwait(false);
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _readLoop = Task.Run(() => ReadLoop(_cts.Token), _cts.Token);
        if (_config.KeepAliveIntervalSeconds is > 0)
        {
            _keepAliveLoop = Task.Run(() => KeepAliveLoop(_cts.Token), _cts.Token);
        }
    }

    public Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct)
    {
        _hasSentAudioSinceLastFinalize = true;
        return _ws.SendBinaryAsync(pcm16Mono, ct);
    }

    public Task EndTurnAsync()
        => SendFinalizeAsync(CancellationToken.None);

    public async Task CloseAsync(TimeSpan timeout)
    {
        var boundedTimeout = timeout > TimeSpan.Zero ? timeout : TimeSpan.FromSeconds(1);
        using var closeCts = new CancellationTokenSource(boundedTimeout);
        if (_ws.State == WebSocketState.Open)
        {
            if (_hasSentAudioSinceLastFinalize)
            {
                await SendFinalizeAsync(closeCts.Token).ConfigureAwait(false);
            }
            MarkCloseStreamSent();
            await _ws.SendTextAsync("{\"type\":\"CloseStream\"}", closeCts.Token).ConfigureAwait(false);
            await DrainIncomingAfterCloseStreamAsync(boundedTimeout).ConfigureAwait(false);
        }
        _cts?.Cancel();
        if (_ws.State == WebSocketState.Open)
        {
            using var transportCloseCts = new CancellationTokenSource(TransportCloseTimeout);
            await _ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "client done", transportCloseCts.Token).ConfigureAwait(false);
        }
        if (_readLoop is { } loop)
        {
            try { await loop.WaitAsync(TransportCloseTimeout).ConfigureAwait(false); } catch { /* ignore */ }
        }
        if (_keepAliveLoop is { } keepAliveLoop)
        {
            try { await keepAliveLoop.WaitAsync(TransportCloseTimeout).ConfigureAwait(false); } catch { /* ignore */ }
        }
        _events.Writer.TryComplete();
    }

    public async ValueTask DisposeAsync()
    {
        try { await CloseAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false); } catch { /* ignore */ }
        await _ws.DisposeAsync().ConfigureAwait(false);
    }

    private async Task ReadLoop(CancellationToken ct)
    {
        var buf = new byte[16384];
        var sb = new StringBuilder(16384);
        try
        {
            while (!ct.IsCancellationRequested && _ws.State == WebSocketState.Open)
            {
                var res = await _ws.ReceiveAsync(buf, ct).ConfigureAwait(false);
                if (res.MessageType == WebSocketMessageType.Close)
                {
                    await _events.Writer.WriteAsync(new TranscriptionEvent.Disconnected(res.CloseStatusDescription), ct).ConfigureAwait(false);
                    break;
                }
                if (res.MessageType != WebSocketMessageType.Text) continue;
                sb.Append(Encoding.UTF8.GetString(buf, 0, res.Count));
                if (!res.EndOfMessage) continue;
                var json = sb.ToString();
                sb.Clear();
                Handle(json);
            }
        }
        catch (OperationCanceledException) { /* normal */ }
        catch (Exception ex)
        {
            await _events.Writer.WriteAsync(new TranscriptionEvent.Disconnected(ex.Message), CancellationToken.None).ConfigureAwait(false);
        }
        finally
        {
            _events.Writer.TryComplete();
        }
    }

    private void Handle(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (!root.TryGetProperty("type", out var typeEl)) return;
        var type = typeEl.GetString();

        switch (type)
        {
            case "Results":
                HandleResults(root);
                break;
            case "Metadata":
                if (HasProviderFlushBeenRequested())
                {
                    MarkTranscriptEvent(finalizationMarker: true);
                }
                break;
            case "error":
            case "Error":
                var (code, message) = DeepgramErrorClassifier.Classify(root);
                _ = _events.Writer.TryWrite(new TranscriptionEvent.ProviderWarning(code, message));
                break;
        }
    }

    private void HandleResults(JsonElement root)
    {
        var fromFinalize = ReadBool(root, "from_finalize");
        if (fromFinalize)
        {
            MarkTranscriptEvent(finalizationMarker: true);
        }

        if (!root.TryGetProperty("channel", out var channel)
            || !channel.TryGetProperty("alternatives", out var alternatives)
            || alternatives.ValueKind != JsonValueKind.Array
            || alternatives.GetArrayLength() == 0)
        {
            return;
        }

        var alternative = alternatives[0];
        var transcript = alternative.TryGetProperty("transcript", out var transcriptElement)
            ? transcriptElement.GetString()
            : null;
        if (string.IsNullOrWhiteSpace(transcript))
        {
            return;
        }

        MarkTranscriptEvent();
        var startMs = SecondsToMs(ReadDouble(root, "start"));
        var durationMs = SecondsToMs(ReadDouble(root, "duration"));
        var endMs = startMs + durationMs;
        var confidence = ReadDouble(alternative, "confidence") ?? 0;
        var isFinal = ReadBool(root, "is_final") || ReadBool(root, "speech_final");
        var speaker = DominantSpeaker(alternative);
        var segment = new LiveTranscriptSegment(transcript, Speaker: speaker, IsFinal: isFinal, StartMs: startMs, EndMs: endMs, Confidence: confidence);

        if (isFinal)
        {
            var key = $"{startMs}:{endMs}:{transcript}";
            if (!_finalSegmentKeys.Add(key))
            {
                return;
            }
            _segments.Add(segment);
            _hasSentAudioSinceLastFinalize = false;
        }

        _ = _events.Writer.TryWrite(new TranscriptionEvent.Transcript(segment));
    }

    /// <summary>
    /// Duration-weighted dominant speaker across the first alternative's words,
    /// returned as a raw <c>"speaker_N"</c> label (or null when Deepgram sent no
    /// diarization). Words with a negative speaker index are ignored; ties are
    /// broken by the lower index. The index is preserved verbatim — display
    /// localization happens later via <c>SpeakerLabelCopy</c>.
    /// </summary>
    private static string? DominantSpeaker(JsonElement alternative)
    {
        if (!alternative.TryGetProperty("words", out var words) || words.ValueKind != JsonValueKind.Array)
        {
            return null;
        }

        var totals = new Dictionary<int, double>();
        foreach (var word in words.EnumerateArray())
        {
            if (!word.TryGetProperty("speaker", out var sp)
                || sp.ValueKind != JsonValueKind.Number
                || !sp.TryGetInt32(out var speaker)
                || speaker < 0)
            {
                continue;
            }

            var start = ReadDouble(word, "start") ?? 0;
            var end = ReadDouble(word, "end") ?? start;
            var weight = Math.Max(0.001, end - start);
            totals[speaker] = totals.TryGetValue(speaker, out var cur) ? cur + weight : weight;
        }

        if (totals.Count == 0)
        {
            return null;
        }

        var dominant = -1;
        var best = double.NegativeInfinity;
        foreach (var kv in totals)
        {
            if (kv.Value > best || (kv.Value == best && kv.Key < dominant))
            {
                best = kv.Value;
                dominant = kv.Key;
            }
        }

        return $"speaker_{dominant}";
    }

    private async Task SendFinalizeAsync(CancellationToken ct)
    {
        if (_ws.State != WebSocketState.Open)
        {
            return;
        }
        MarkEndTurnSent();
        await _ws.SendTextAsync("{\"type\":\"Finalize\"}", ct).ConfigureAwait(false);
        _hasSentAudioSinceLastFinalize = false;
    }

    private async Task DrainIncomingAfterCloseStreamAsync(TimeSpan timeout)
    {
        var startedAt = _drainClock.Elapsed;
        var deadline = startedAt + timeout;

        while (_readLoop is { IsCompleted: false })
        {
            var now = _drainClock.Elapsed;
            var snapshot = DrainSnapshot();
            if (!RealtimeCloseDrainPolicy.ShouldKeepWaiting(
                    now,
                    deadline,
                    startedAt,
                    snapshot.LastTranscriptEventAt,
                    snapshot.FinalizationMarkerReceived))
            {
                return;
            }

            var remaining = deadline - now;
            if (remaining <= TimeSpan.Zero)
            {
                return;
            }

            var delay = remaining < DrainPollInterval ? remaining : DrainPollInterval;
            await Task.Delay(delay).ConfigureAwait(false);
        }
    }

    private void ResetDrainState()
    {
        lock (_drainLock)
        {
            _endTurnSent = false;
            _closeStreamSent = false;
            _lastTranscriptEventAt = null;
            _finalizationMarkerReceived = false;
            _drainClock.Restart();
        }
    }

    private void MarkTranscriptEvent(bool finalizationMarker = false)
    {
        lock (_drainLock)
        {
            _lastTranscriptEventAt = _drainClock.Elapsed;
            if (finalizationMarker)
            {
                _finalizationMarkerReceived = true;
            }
        }
    }

    private void MarkEndTurnSent()
    {
        lock (_drainLock)
        {
            _endTurnSent = true;
        }
    }

    private void MarkCloseStreamSent()
    {
        lock (_drainLock)
        {
            _closeStreamSent = true;
        }
    }

    private bool HasProviderFlushBeenRequested()
    {
        lock (_drainLock)
        {
            return _endTurnSent || _closeStreamSent;
        }
    }

    private (TimeSpan? LastTranscriptEventAt, bool FinalizationMarkerReceived) DrainSnapshot()
    {
        lock (_drainLock)
        {
            return (_lastTranscriptEventAt, _finalizationMarkerReceived);
        }
    }

    private async Task KeepAliveLoop(CancellationToken ct)
    {
        var interval = TimeSpan.FromSeconds(_config.KeepAliveIntervalSeconds!.Value);
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(interval, ct).ConfigureAwait(false);
                if (_ws.State == WebSocketState.Open)
                {
                    await _ws.SendTextAsync("{\"type\":\"KeepAlive\"}", ct).ConfigureAwait(false);
                }
            }
        }
        catch (OperationCanceledException)
        {
            // Normal session shutdown.
        }
    }

    private void ValidateConfig()
    {
        if (_config.Provider != RealtimeProvider.Deepgram)
        {
            throw new InvalidOperationException($"Deepgram session received unsupported provider: {_config.Provider}");
        }
        if (_config.AuthScheme != AuthScheme.Bearer)
        {
            throw new InvalidOperationException($"Deepgram session requires bearer auth, got {_config.AuthScheme}");
        }
        if (string.IsNullOrWhiteSpace(_config.WebSocketUrl))
        {
            throw new InvalidOperationException("Deepgram session requires websocket_url");
        }
        if (string.IsNullOrWhiteSpace(_config.Token))
        {
            throw new InvalidOperationException("Deepgram session requires token");
        }
        if (_config.SampleRate != 16000 || _config.AudioFormat != "linear16" || _config.Channels != 1)
        {
            throw new InvalidOperationException("Deepgram session requires 16 kHz mono linear16 audio");
        }
    }

    private static bool ReadBool(JsonElement root, string name)
        => root.TryGetProperty(name, out var value)
           && value.ValueKind is JsonValueKind.True or JsonValueKind.False
           && value.GetBoolean();

    private static double? ReadDouble(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value))
        {
            return null;
        }
        return value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var result) ? result : null;
    }

    private static int SecondsToMs(double? value)
        => (int)Math.Round((value ?? 0) * 1000, MidpointRounding.AwayFromZero);
}
