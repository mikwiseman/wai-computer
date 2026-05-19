using System.Net.WebSockets;
using System.Text.Json;
using System.Threading.Channels;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// Inworld realtime transcription. Auth: short-lived
/// <c>Authorization: Bearer …</c> JWT minted server-side. Audio: base64 PCM
/// JSON frames using the current camelCase streaming protocol.
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
            options.SetRequestHeader("Authorization", $"Bearer {_config.Token}");
        }, ct).ConfigureAwait(false);

        await _events.Writer.WriteAsync(new TranscriptionEvent.Connected(), ct).ConfigureAwait(false);
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _readLoop = Task.Run(() => ReadLoop(_cts.Token), _cts.Token);
        await _ws.SendTextAsync(TranscribeConfigPayload(), ct).ConfigureAwait(false);
    }

    public Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct)
        => _ws.SendTextAsync(AudioChunkPayload(pcm16Mono.Span), ct);

    public Task EndTurnAsync()
        => _ws.SendTextAsync("{\"endTurn\":{}}", CancellationToken.None);

    public async Task CloseAsync(TimeSpan timeout)
    {
        if (_ws.State == WebSocketState.Open)
        {
            try { await EndTurnAsync().ConfigureAwait(false); } catch { /* close continues */ }
            try { await _ws.SendTextAsync("{\"closeStream\":{}}", CancellationToken.None).ConfigureAwait(false); } catch { /* close continues */ }
        }

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

    private string TranscribeConfigPayload()
        => JsonSerializer.Serialize(new
        {
            transcribeConfig = new
            {
                modelId = _config.Model,
                audioEncoding = "LINEAR16",
                sampleRateHertz = _config.SampleRate,
                numberOfChannels = _config.Channels,
                language = _config.Language is "multi" ? string.Empty : _config.Language,
            },
        });

    private string AudioChunkPayload(ReadOnlySpan<byte> pcm)
        => JsonSerializer.Serialize(new
        {
            audioChunk = new
            {
                content = Convert.ToBase64String(pcm),
            },
        });

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

        if (!TryGetTranscription(root, out var trans)) return;
        var text = trans.TryGetProperty("transcript", out var transcript)
            ? transcript.GetString() ?? string.Empty
            : trans.TryGetProperty("text", out var textElement)
                ? textElement.GetString() ?? string.Empty
                : string.Empty;
        if (string.IsNullOrEmpty(text)) return;

        var isFinal = TryGetBoolean(trans, "isFinal") ?? TryGetBoolean(trans, "is_final") ?? false;
        var (speaker, start, end) = WordMetadata(trans);
        if (start == 0 && trans.TryGetProperty("start_ms", out var s) && s.TryGetInt64(out var sv)) start = sv;
        if (end == 0 && trans.TryGetProperty("end_ms", out var e) && e.TryGetInt64(out var ev)) end = ev;
        var confidence = trans.TryGetProperty("confidence", out var c) && c.TryGetDouble(out var cv) ? cv : 1.0;
        var seg = new LiveTranscriptSegment(text, speaker, isFinal, start, end, confidence);
        if (isFinal) _segments.Add(seg);
        _ = _events.Writer.TryWrite(new TranscriptionEvent.Transcript(seg));
    }

    private static bool? TryGetBoolean(JsonElement root, string property)
        => root.TryGetProperty(property, out var value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? value.GetBoolean()
            : null;

    private static bool TryGetTranscription(JsonElement root, out JsonElement transcription)
    {
        if (root.TryGetProperty("transcription", out transcription))
        {
            return true;
        }

        if (root.TryGetProperty("result", out var result)
            && result.TryGetProperty("transcription", out transcription))
        {
            return true;
        }

        transcription = default;
        return false;
    }

    private static (string? Speaker, long StartMs, long EndMs) WordMetadata(JsonElement transcription)
    {
        if (!transcription.TryGetProperty("wordTimestamps", out var words)
            || words.ValueKind != JsonValueKind.Array
            || words.GetArrayLength() == 0)
        {
            return (null, 0, 0);
        }

        var first = words[0];
        var last = words[words.GetArrayLength() - 1];
        var startMs = first.TryGetProperty("startMs", out var start) && start.TryGetInt64(out var startValue)
            ? startValue
            : 0L;
        var endMs = last.TryGetProperty("endMs", out var end) && end.TryGetInt64(out var endValue)
            ? endValue
            : startMs;
        var speaker = first.TryGetProperty("speaker", out var speakerElement) && speakerElement.ValueKind == JsonValueKind.String
            ? speakerElement.GetString()
            : null;

        return (speaker, startMs, endMs);
    }
}
