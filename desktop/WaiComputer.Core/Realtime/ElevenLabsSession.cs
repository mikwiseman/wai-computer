using System.Net.WebSockets;
using System.Text.Json;
using System.Threading.Channels;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// ElevenLabs realtime STT.
/// URL: <c>wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=…&amp;token=…&amp;audio_format=pcm_16000&amp;include_timestamps=true</c>.
/// Auth: query token. Audio: base64 PCM JSON frames. Commit: explicit
/// final chunk so the tail of dictation is flushed before closing.
/// </summary>
public sealed class ElevenLabsSession : IRealtimeTranscriptionSession
{
    private const int CommitPaddingMs = 220;
    private readonly RealtimeTranscriptionSessionConfig _config;
    private readonly IWebSocketTransport _ws;
    private readonly List<LiveTranscriptSegment> _segments = new();
    private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>(
        new UnboundedChannelOptions { SingleReader = true });

    private Task? _readLoop;
    private CancellationTokenSource? _cts;

    public RealtimeProvider Provider => RealtimeProvider.ElevenLabs;
    public IAsyncEnumerable<TranscriptionEvent> Events => _events.Reader.ReadAllAsync();
    public IReadOnlyList<LiveTranscriptSegment> CollectedSegments => _segments;

    public ElevenLabsSession(RealtimeTranscriptionSessionConfig config, IWebSocketTransport? transport = null)
    {
        _config = config;
        _ws = transport ?? new ClientWebSocketTransport();
    }

    public async Task OpenAsync(CancellationToken ct)
    {
        var url = _config.WebSocketUrl ??
            $"wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id={Uri.EscapeDataString(_config.Model)}&token={Uri.EscapeDataString(_config.Token)}&audio_format=pcm_16000&include_timestamps=true";

        await _ws.ConnectAsync(new Uri(url), configure: null, ct).ConfigureAwait(false);
        await _events.Writer.WriteAsync(new TranscriptionEvent.Connected(), ct).ConfigureAwait(false);
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _readLoop = Task.Run(() => ReadLoop(_cts.Token), _cts.Token);
    }

    public Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct)
        => _ws.SendTextAsync(AudioChunkPayload(pcm16Mono.Span, commit: false), ct);

    public Task EndTurnAsync()
    {
        var paddingBytes = Math.Max(1, _config.SampleRate * CommitPaddingMs / 1000) * 2;
        return _ws.SendTextAsync(AudioChunkPayload(new byte[paddingBytes], commit: true), CancellationToken.None);
    }

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

    private string AudioChunkPayload(ReadOnlySpan<byte> pcm, bool commit)
        => JsonSerializer.Serialize(new
        {
            message_type = "input_audio_chunk",
            audio_base_64 = Convert.ToBase64String(pcm),
            sample_rate = _config.SampleRate,
            commit,
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
                var json = sb.ToString();
                sb.Clear();
                HandleMessage(json, ct);
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

    private void HandleMessage(string json, CancellationToken ct)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (!root.TryGetProperty("message_type", out var typeEl)) return;
        var type = typeEl.GetString();

        switch (type)
        {
            case "session_started":
                break;
            case "partial_transcript":
                EmitSegment(root, isFinal: false, ct);
                break;
            case "committed_transcript_with_timestamps":
            case "committed_transcript":
                EmitSegment(root, isFinal: true, ct);
                break;
            case "error":
                var code = root.TryGetProperty("error", out var er) && er.ValueKind == JsonValueKind.String
                    ? er.GetString() ?? TranscriptionErrorCodes.GenericError
                    : TranscriptionErrorCodes.GenericError;
                var msg = root.TryGetProperty("message", out var m) && m.ValueKind == JsonValueKind.String
                    ? m.GetString() ?? "Provider error"
                    : "Provider error";
                _ = _events.Writer.TryWrite(new TranscriptionEvent.ProviderWarning(code, msg));
                break;
        }
    }

    private void EmitSegment(JsonElement root, bool isFinal, CancellationToken ct)
    {
        var text = root.TryGetProperty("text", out var t) && t.ValueKind == JsonValueKind.String
            ? t.GetString() ?? string.Empty
            : string.Empty;
        if (string.IsNullOrEmpty(text)) return;

        var start = root.TryGetProperty("start_ms", out var s) && s.TryGetInt64(out var sv) ? sv : 0L;
        var end = root.TryGetProperty("end_ms", out var e) && e.TryGetInt64(out var ev) ? ev : start;
        var confidence = root.TryGetProperty("confidence", out var c) && c.TryGetDouble(out var cv) ? cv : 1.0;

        var seg = new LiveTranscriptSegment(text, Speaker: null, IsFinal: isFinal, StartMs: start, EndMs: end, Confidence: confidence);
        if (isFinal) _segments.Add(seg);
        _ = _events.Writer.TryWrite(new TranscriptionEvent.Transcript(seg));
    }
}
