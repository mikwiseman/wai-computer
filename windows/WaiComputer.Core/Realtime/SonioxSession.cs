using System.Net.WebSockets;
using System.Text.Json;
using System.Threading.Channels;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// Soniox realtime transcription. Auth: temporary API key sent in the first
/// config message, never as a URL query parameter. Audio: raw PCM binary.
/// </summary>
public sealed class SonioxSession : IRealtimeTranscriptionSession
{
    private readonly RealtimeTranscriptionSessionConfig _config;
    private readonly IWebSocketTransport _ws;
    private readonly List<LiveTranscriptSegment> _segments = new();
    private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>(
        new UnboundedChannelOptions { SingleReader = true });

    private Task? _readLoop;
    private CancellationTokenSource? _cts;

    public RealtimeProvider Provider => RealtimeProvider.Soniox;
    public IAsyncEnumerable<TranscriptionEvent> Events => _events.Reader.ReadAllAsync();
    public IReadOnlyList<LiveTranscriptSegment> CollectedSegments => _segments;

    public SonioxSession(RealtimeTranscriptionSessionConfig config, IWebSocketTransport? transport = null)
    {
        _config = config;
        _ws = transport ?? new ClientWebSocketTransport();
    }

    public async Task OpenAsync(CancellationToken ct)
    {
        var url = _config.WebSocketUrl ?? throw new InvalidOperationException("Soniox session requires websocket_url");
        await _ws.ConnectAsync(new Uri(url), configure: null, ct).ConfigureAwait(false);
        await _ws.SendTextAsync(ConfigPayload(), ct).ConfigureAwait(false);
        await _events.Writer.WriteAsync(new TranscriptionEvent.Connected(), ct).ConfigureAwait(false);
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _readLoop = Task.Run(() => ReadLoop(_cts.Token), _cts.Token);
    }

    public Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct)
        => _ws.SendBinaryAsync(pcm16Mono, ct);

    public async Task EndTurnAsync()
    {
        var silenceBytes = Math.Max(1, _config.SampleRate / 5) * 2;
        await _ws.SendBinaryAsync(new byte[silenceBytes], CancellationToken.None).ConfigureAwait(false);
        await _ws.SendTextAsync("{\"type\":\"finalize\"}", CancellationToken.None).ConfigureAwait(false);
    }

    public async Task CloseAsync(TimeSpan timeout)
    {
        if (_ws.State == WebSocketState.Open)
        {
            try { await EndTurnAsync().ConfigureAwait(false); } catch { /* close continues */ }
            try { await _ws.SendTextAsync(string.Empty, CancellationToken.None).ConfigureAwait(false); } catch { /* close continues */ }
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

    private string ConfigPayload()
    {
        var payload = new Dictionary<string, object>
        {
            ["api_key"] = _config.Token,
            ["model"] = _config.Model,
            ["audio_format"] = "pcm_s16le",
            ["sample_rate"] = _config.SampleRate,
            ["num_channels"] = _config.Channels,
            ["enable_speaker_diarization"] = true,
            ["enable_language_identification"] = _config.Language is "multi",
            ["enable_endpoint_detection"] = true,
            ["max_endpoint_delay_ms"] = 500,
        };
        if (_config.Language is { Length: > 0 } && _config.Language != "multi")
        {
            payload["language_hints"] = new[] { _config.Language };
        }

        return JsonSerializer.Serialize(payload);
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
                Handle(sb.ToString());
                sb.Clear();
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

        if (root.TryGetProperty("error_code", out var errorCode))
        {
            var code = errorCode.ValueKind == JsonValueKind.String ? errorCode.GetString() : TranscriptionErrorCodes.GenericError;
            var message = root.TryGetProperty("error_message", out var errorMessage) && errorMessage.ValueKind == JsonValueKind.String
                ? errorMessage.GetString()
                : "Soniox realtime error";
            _ = _events.Writer.TryWrite(new TranscriptionEvent.ProviderWarning(code ?? TranscriptionErrorCodes.GenericError, message ?? "Soniox realtime error"));
            return;
        }

        if (!root.TryGetProperty("tokens", out var tokens) || tokens.ValueKind != JsonValueKind.Array || tokens.GetArrayLength() == 0)
        {
            return;
        }

        EmitTokens(tokens, isFinal: true);
        EmitTokens(tokens, isFinal: false);
    }

    private void EmitTokens(JsonElement tokens, bool isFinal)
    {
        var selected = tokens.EnumerateArray()
            .Where(token => token.TryGetProperty("is_final", out var final) && final.ValueKind is JsonValueKind.True or JsonValueKind.False && final.GetBoolean() == isFinal)
            .ToArray();
        if (selected.Length == 0) return;

        var text = string.Concat(selected.Select(TokenText));
        if (string.IsNullOrWhiteSpace(text)) return;

        var first = selected[0];
        var last = selected[^1];
        var startMs = TokenTimestampMs(first, "start_ms", "start");
        var endMs = TokenTimestampMs(last, "end_ms", "end");
        var confidence = selected
            .Select(token => token.TryGetProperty("confidence", out var confidenceElement) && confidenceElement.TryGetDouble(out var value) ? value : (double?)null)
            .Where(value => value.HasValue)
            .Select(value => value!.Value)
            .DefaultIfEmpty(1.0)
            .Average();
        var speaker = first.TryGetProperty("speaker", out var speakerElement) && speakerElement.ValueKind == JsonValueKind.String
            ? speakerElement.GetString()
            : null;

        var seg = new LiveTranscriptSegment(text, speaker, isFinal, startMs, endMs, confidence);
        if (isFinal) _segments.Add(seg);
        _ = _events.Writer.TryWrite(new TranscriptionEvent.Transcript(seg));
    }

    private static string TokenText(JsonElement token)
    {
        if (!token.TryGetProperty("text", out var text) || text.ValueKind != JsonValueKind.String)
        {
            return string.Empty;
        }
        var value = text.GetString() ?? string.Empty;
        return value.StartsWith('<') ? string.Empty : value;
    }

    private static long TokenTimestampMs(JsonElement token, string millisecondsProperty, string secondsProperty)
    {
        if (token.TryGetProperty(millisecondsProperty, out var milliseconds) && milliseconds.TryGetInt64(out var ms))
        {
            return ms;
        }
        if (token.TryGetProperty(secondsProperty, out var seconds) && seconds.TryGetDouble(out var s))
        {
            return (long)Math.Round(s * 1000);
        }
        return 0L;
    }
}
