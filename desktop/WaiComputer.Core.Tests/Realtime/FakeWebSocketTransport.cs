using System.Net.WebSockets;
using System.Text;
using System.Threading.Channels;
using WaiComputer.Core.Realtime;

namespace WaiComputer.Core.Tests.Realtime;

/// <summary>
/// In-memory <see cref="IWebSocketTransport"/> used by every provider session
/// test. Backed by two channels: server→client (messages we inject as the
/// "remote") and client→server (messages produced by the session, observable
/// for assertions).
/// </summary>
public sealed class FakeWebSocketTransport : IWebSocketTransport
{
    private readonly Channel<(WebSocketMessageType, byte[])> _incoming = Channel.CreateUnbounded<(WebSocketMessageType, byte[])>();
    public List<string> SentText { get; } = new();
    public List<byte[]> SentBinary { get; } = new();
    public List<KeyValuePair<string, string>> Headers { get; } = new();
    public Uri? ConnectedTo { get; private set; }

    public WebSocketState State { get; private set; } = WebSocketState.None;

    public Task ConnectAsync(Uri uri, Action<ClientWebSocketOptions>? configure, CancellationToken ct)
    {
        ConnectedTo = uri;
        _ = configure;
        State = WebSocketState.Open;
        return Task.CompletedTask;
    }

    public void CaptureHeader(string name, string value) => Headers.Add(new(name, value));

    public Task SendTextAsync(string payload, CancellationToken ct)
    {
        SentText.Add(payload);
        return Task.CompletedTask;
    }

    public Task SendBinaryAsync(ReadOnlyMemory<byte> payload, CancellationToken ct)
    {
        SentBinary.Add(payload.ToArray());
        return Task.CompletedTask;
    }

    public async Task<WebSocketReceiveResult> ReceiveAsync(Memory<byte> buffer, CancellationToken ct)
    {
        var (type, payload) = await _incoming.Reader.ReadAsync(ct).ConfigureAwait(false);
        if (type == WebSocketMessageType.Close)
        {
            State = WebSocketState.Closed;
            return new WebSocketReceiveResult(0, type, true, WebSocketCloseStatus.NormalClosure, "test close");
        }
        var bytes = payload.AsSpan();
        var n = Math.Min(bytes.Length, buffer.Length);
        bytes[..n].CopyTo(buffer.Span);
        return new WebSocketReceiveResult(n, type, endOfMessage: true);
    }

    public Task CloseAsync(WebSocketCloseStatus status, string? description, CancellationToken ct)
    {
        State = WebSocketState.Closed;
        _incoming.Writer.TryWrite((WebSocketMessageType.Close, Array.Empty<byte>()));
        _incoming.Writer.TryComplete();
        return Task.CompletedTask;
    }

    public void PushText(string json) => _incoming.Writer.TryWrite((WebSocketMessageType.Text, Encoding.UTF8.GetBytes(json)));
    public void PushClose() => _incoming.Writer.TryWrite((WebSocketMessageType.Close, Array.Empty<byte>()));

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;
}
