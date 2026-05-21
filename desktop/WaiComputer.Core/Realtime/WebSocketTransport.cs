using System.Net.WebSockets;
using System.Text;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// Thin async wrapper over <see cref="ClientWebSocket"/> with TextFrame / BinaryFrame
/// helpers and graceful close. Centralises the per-provider session code on a
/// single API surface so tests can substitute an in-memory transport.
/// </summary>
public interface IWebSocketTransport : IAsyncDisposable
{
    WebSocketState State { get; }
    Task ConnectAsync(Uri uri, Action<ClientWebSocketOptions>? configure, CancellationToken ct);
    Task SendTextAsync(string payload, CancellationToken ct);
    Task SendBinaryAsync(ReadOnlyMemory<byte> payload, CancellationToken ct);
    Task<WebSocketReceiveResult> ReceiveAsync(Memory<byte> buffer, CancellationToken ct);
    Task CloseAsync(WebSocketCloseStatus status, string? description, CancellationToken ct);
}

public sealed class ClientWebSocketTransport : IWebSocketTransport
{
    private ClientWebSocket _ws = new();

    public WebSocketState State => _ws.State;

    public async Task ConnectAsync(Uri uri, Action<ClientWebSocketOptions>? configure, CancellationToken ct)
    {
        _ws = new ClientWebSocket();
        configure?.Invoke(_ws.Options);
        await _ws.ConnectAsync(uri, ct).ConfigureAwait(false);
    }

    public Task SendTextAsync(string payload, CancellationToken ct)
        => _ws.SendAsync(new ArraySegment<byte>(Encoding.UTF8.GetBytes(payload)),
            WebSocketMessageType.Text, endOfMessage: true, ct);

    public Task SendBinaryAsync(ReadOnlyMemory<byte> payload, CancellationToken ct)
        => _ws.SendAsync(payload, WebSocketMessageType.Binary, endOfMessage: true, ct).AsTask();

    public async Task<WebSocketReceiveResult> ReceiveAsync(Memory<byte> buffer, CancellationToken ct)
    {
        var v = await _ws.ReceiveAsync(buffer, ct).ConfigureAwait(false);
        return new WebSocketReceiveResult(
            v.Count,
            v.MessageType,
            v.EndOfMessage,
            _ws.CloseStatus,
            _ws.CloseStatusDescription);
    }

    public async Task CloseAsync(WebSocketCloseStatus status, string? description, CancellationToken ct)
    {
        if (_ws.State == WebSocketState.Open)
        {
            try { await _ws.CloseAsync(status, description, ct).ConfigureAwait(false); }
            catch { /* swallow */ }
        }
    }

    public ValueTask DisposeAsync()
    {
        _ws.Dispose();
        return ValueTask.CompletedTask;
    }
}
