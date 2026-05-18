using System.Net.WebSockets;
using System.Text.Json;
using System.Threading.Channels;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// Inworld realtime transcription. Auth: pre-built
/// <c>Authorization: Basic …</c> string supplied by the WaiComputer backend.
/// Audio: raw binary PCM. Commit: server VAD.
/// </summary>
public sealed class InworldSession : IRealtimeTranscriptionSession
{
    private readonly RealtimeTranscriptionSessionConfig _config;
    private readonly IWebSocketTransport _ws;
    private readonly List<LiveTranscriptSegment> _segments = new();
    private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>(
        new UnboundedChannelOptions { SingleReader = true });
    private Task? _readLoop;
    private CancellationTokenSource? _cts;

    public RealtimeProvider Provider => RealtimeProvider.Inworld;
    public IAsyncEnumerable<TranscriptionEvent> Events => _events.Reader.ReadAllAsync();
    public IReadOnlyList<LiveTranscriptSegment> CollectedSegments => _segments;

    public InworldSession(RealtimeTranscriptionSessionConfig config, IWebSocketTransport? transport = null)
    {
        _config = config;
        _ws = transport ?? new ClientWebSocketTransport();
    }

    public async Task OpenAsync(CancellationToken ct)
    {
        var url = _config.WebSocketUrl ?? throw new InvalidOperationException("Inworld session requires websocket_url");
        await _ws.ConnectAsync(new Uri(url), options =>
        {
            options.SetRequestHeader("Authorization", _config.Token); // backend pre-builds "Basic …"
        }, ct).ConfigureAwait(false);

        await _events.Writer.WriteAsync(new TranscriptionEvent.Connected(), ct).ConfigureAwait(false);
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _readLoop = Task.Run(() => ReadLoop(_cts.Token), _cts.Token);
    }

    public Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct)
        => _ws.SendBinaryAsync(pcm16Mono, ct);

    public Task EndTurnAsync() => Task.CompletedTask;

    public async Task CloseAsync(TimeSpan timeout)
    {
        _cts?.Cancel();
        using var closeCts = new CancellationTokenSource(timeout);
        await _ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "client done", closeCts.Token).ConfigureAwait(false);
        if (_readLoop is { } loop)
        {
            try { await loop.WaitAsync(closeCts.Token).ConfigureAwait(false); } catch { /* ignore */ }
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
        var buf = new byte[8192];
        var sb = new System.Text.StringBuilder(8192);
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
                sb.Append(System.Text.Encoding.UTF8.GetString(buf, 0, res.Count));
                if (!res.EndOfMessage) continue;
                Handle(sb.ToString());
                sb.Clear();
            }
        }
        catch (OperationCanceledException) { }
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

        if (root.TryGetProperty("error", out var err) && err.TryGetProperty("message", out var msg))
        {
            _ = _events.Writer.TryWrite(new TranscriptionEvent.ProviderWarning(TranscriptionErrorCodes.GenericError, msg.GetString() ?? "Inworld error"));
            return;
        }

        if (!root.TryGetProperty("transcription", out var trans)) return;
        var text = trans.TryGetProperty("text", out var t) ? t.GetString() ?? string.Empty : string.Empty;
        if (string.IsNullOrEmpty(text)) return;

        var isFinal = trans.TryGetProperty("is_final", out var f) && f.GetBoolean();
        var start = trans.TryGetProperty("start_ms", out var s) && s.TryGetInt64(out var sv) ? sv : 0L;
        var end = trans.TryGetProperty("end_ms", out var e) && e.TryGetInt64(out var ev) ? ev : start;
        var confidence = trans.TryGetProperty("confidence", out var c) && c.TryGetDouble(out var cv) ? cv : 1.0;
        var seg = new LiveTranscriptSegment(text, Speaker: null, IsFinal: isFinal, StartMs: start, EndMs: end, Confidence: confidence);
        if (isFinal) _segments.Add(seg);
        _ = _events.Writer.TryWrite(new TranscriptionEvent.Transcript(seg));
    }
}
