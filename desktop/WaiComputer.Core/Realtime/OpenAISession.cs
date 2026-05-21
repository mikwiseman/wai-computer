using System.Net.WebSockets;
using System.Text.Json;
using System.Threading.Channels;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// OpenAI realtime transcription.
/// Auth: <c>Authorization: Bearer …</c>. Audio: base64-encoded PCM inside
/// JSON <c>input_audio_buffer.append</c> events. Commit: manual via
/// <c>input_audio_buffer.commit</c>.
/// </summary>
public sealed class OpenAISession : IRealtimeTranscriptionSession
{
    private readonly RealtimeTranscriptionSessionConfig _config;
    private readonly IWebSocketTransport _ws;
    private readonly List<LiveTranscriptSegment> _segments = new();
    private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>(
        new UnboundedChannelOptions { SingleReader = true });
    private readonly Dictionary<string, System.Text.StringBuilder> _interimByItem = new();

    private Task? _readLoop;
    private CancellationTokenSource? _cts;

    public RealtimeProvider Provider => RealtimeProvider.OpenAi;
    public IAsyncEnumerable<TranscriptionEvent> Events => _events.Reader.ReadAllAsync();
    public IReadOnlyList<LiveTranscriptSegment> CollectedSegments => _segments;

    public OpenAISession(RealtimeTranscriptionSessionConfig config, IWebSocketTransport? transport = null)
    {
        _config = config;
        _ws = transport ?? new ClientWebSocketTransport();
    }

    public async Task OpenAsync(CancellationToken ct)
    {
        var url = _config.WebSocketUrl ?? throw new InvalidOperationException("OpenAI session requires websocket_url");
        await _ws.ConnectAsync(new Uri(url), options =>
        {
            options.SetRequestHeader("Authorization", $"Bearer {_config.Token}");
        }, ct).ConfigureAwait(false);

        await _events.Writer.WriteAsync(new TranscriptionEvent.Connected(), ct).ConfigureAwait(false);
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _readLoop = Task.Run(() => ReadLoop(_cts.Token), _cts.Token);

        var transcription = _config.Language is { Length: > 0 } && _config.Language != "multi"
            ? new Dictionary<string, object> { ["model"] = _config.Model, ["language"] = _config.Language }
            : new Dictionary<string, object> { ["model"] = _config.Model };

        var sessionUpdate = JsonSerializer.Serialize(new
        {
            type = "session.update",
            session = new
            {
                type = "transcription",
                audio = new
                {
                    input = new
                    {
                        format = new { type = "audio/pcm", rate = _config.SampleRate },
                        transcription,
                        turn_detection = (object?)null,
                    },
                },
            },
        });
        await _ws.SendTextAsync(sessionUpdate, ct).ConfigureAwait(false);
    }

    public Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct)
    {
        var payload = JsonSerializer.Serialize(new
        {
            type = "input_audio_buffer.append",
            audio = Convert.ToBase64String(pcm16Mono.Span),
        });
        return _ws.SendTextAsync(payload, ct);
    }

    public Task EndTurnAsync()
        => _ws.SendTextAsync("{\"type\":\"input_audio_buffer.commit\"}", CancellationToken.None);

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
        var buf = new byte[16384];
        var sb = new System.Text.StringBuilder(16384);
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
            case "conversation.item.input_audio_transcription.delta":
                AccumulateDelta(root);
                break;
            case "conversation.item.input_audio_transcription.completed":
                FinaliseItem(root);
                break;
            case "error":
                var msg = root.TryGetProperty("error", out var e) && e.TryGetProperty("message", out var m) ? m.GetString() : "OpenAI error";
                _ = _events.Writer.TryWrite(new TranscriptionEvent.ProviderWarning(TranscriptionErrorCodes.GenericError, msg ?? "OpenAI error"));
                break;
        }
    }

    private void AccumulateDelta(JsonElement root)
    {
        var itemId = root.GetProperty("item_id").GetString() ?? Guid.NewGuid().ToString();
        var delta = root.GetProperty("delta").GetString() ?? string.Empty;
        if (!_interimByItem.TryGetValue(itemId, out var sb))
        {
            sb = new System.Text.StringBuilder();
            _interimByItem[itemId] = sb;
        }
        sb.Append(delta);
        var seg = new LiveTranscriptSegment(sb.ToString(), Speaker: null, IsFinal: false, StartMs: 0, EndMs: 0, Confidence: 0);
        _ = _events.Writer.TryWrite(new TranscriptionEvent.Transcript(seg));
    }

    private void FinaliseItem(JsonElement root)
    {
        var itemId = root.GetProperty("item_id").GetString() ?? Guid.NewGuid().ToString();
        var text = root.TryGetProperty("transcript", out var t) ? t.GetString() : null;
        if (string.IsNullOrEmpty(text) && _interimByItem.TryGetValue(itemId, out var sb))
        {
            text = sb.ToString();
        }
        _interimByItem.Remove(itemId);
        if (string.IsNullOrEmpty(text)) return;

        var seg = new LiveTranscriptSegment(text, Speaker: null, IsFinal: true, StartMs: 0, EndMs: 0, Confidence: 1.0);
        _segments.Add(seg);
        _ = _events.Writer.TryWrite(new TranscriptionEvent.Transcript(seg));
    }
}
