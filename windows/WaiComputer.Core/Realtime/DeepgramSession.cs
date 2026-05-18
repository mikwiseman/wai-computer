using System.Net.WebSockets;
using System.Text.Json;
using System.Threading.Channels;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// Deepgram realtime transcription. Auth: <c>Authorization: Token …</c>.
/// Audio: raw binary PCM. Commit: server VAD. Requires periodic keep-alive
/// JSON pings; interval comes from
/// <see cref="RealtimeTranscriptionSessionConfig.KeepAliveIntervalSeconds"/>.
/// </summary>
public sealed class DeepgramSession : IRealtimeTranscriptionSession
{
    private readonly RealtimeTranscriptionSessionConfig _config;
    private readonly IWebSocketTransport _ws;
    private readonly List<LiveTranscriptSegment> _segments = new();
    private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>(
        new UnboundedChannelOptions { SingleReader = true });
    private Task? _readLoop;
    private Task? _keepAlive;
    private CancellationTokenSource? _cts;

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
        var url = _config.WebSocketUrl ?? throw new InvalidOperationException("Deepgram session requires websocket_url");
        await _ws.ConnectAsync(new Uri(url), options =>
        {
            options.SetRequestHeader("Authorization", $"Token {_config.Token}");
        }, ct).ConfigureAwait(false);

        await _events.Writer.WriteAsync(new TranscriptionEvent.Connected(), ct).ConfigureAwait(false);
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _readLoop = Task.Run(() => ReadLoop(_cts.Token), _cts.Token);
        if (_config.KeepAliveIntervalSeconds is int seconds && seconds > 0)
        {
            _keepAlive = Task.Run(() => KeepAlive(TimeSpan.FromSeconds(seconds), _cts.Token), _cts.Token);
        }
    }

    public Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct)
        => _ws.SendBinaryAsync(pcm16Mono, ct);

    public Task EndTurnAsync() => Task.CompletedTask;

    public async Task CloseAsync(TimeSpan timeout)
    {
        _cts?.Cancel();
        using var closeCts = new CancellationTokenSource(timeout);
        await _ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "client done", closeCts.Token).ConfigureAwait(false);
        if (_readLoop is { } loop) { try { await loop.WaitAsync(closeCts.Token).ConfigureAwait(false); } catch { } }
        if (_keepAlive is { } k) { try { await k.WaitAsync(closeCts.Token).ConfigureAwait(false); } catch { } }
        _events.Writer.TryComplete();
    }

    public async ValueTask DisposeAsync()
    {
        try { await CloseAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false); } catch { /* ignore */ }
        await _ws.DisposeAsync().ConfigureAwait(false);
    }

    private async Task KeepAlive(TimeSpan interval, CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try { await Task.Delay(interval, ct).ConfigureAwait(false); }
            catch (OperationCanceledException) { return; }
            try { await _ws.SendTextAsync("{\"type\":\"KeepAlive\"}", ct).ConfigureAwait(false); }
            catch { /* surface via read loop on next failure */ }
        }
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
        if (!root.TryGetProperty("type", out var typeEl)) return;
        var type = typeEl.GetString();
        if (type != "Results") return;
        if (!root.TryGetProperty("channel", out var ch)) return;
        if (!ch.TryGetProperty("alternatives", out var alts) || alts.ValueKind != JsonValueKind.Array) return;
        if (alts.GetArrayLength() == 0) return;
        var alt = alts[0];
        var text = alt.TryGetProperty("transcript", out var t) ? t.GetString() : null;
        if (string.IsNullOrEmpty(text)) return;
        var isFinal = root.TryGetProperty("is_final", out var f) && f.GetBoolean();
        var confidence = alt.TryGetProperty("confidence", out var c) && c.TryGetDouble(out var cv) ? cv : 1.0;
        var seg = new LiveTranscriptSegment(text, Speaker: null, IsFinal: isFinal, StartMs: 0, EndMs: 0, Confidence: confidence);
        if (isFinal) _segments.Add(seg);
        _ = _events.Writer.TryWrite(new TranscriptionEvent.Transcript(seg));
    }
}
