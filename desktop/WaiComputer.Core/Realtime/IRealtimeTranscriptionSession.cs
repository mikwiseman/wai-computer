using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// Common surface for a per-provider realtime transcription session.
/// Implementations encode the provider's auth scheme, audio framing
/// and finalization strategy.
/// </summary>
public interface IRealtimeTranscriptionSession : IAsyncDisposable
{
    RealtimeProvider Provider { get; }
    /// <summary>
    /// Final + interim transcripts + lifecycle events. Open the session, then
    /// iterate this stream until you call <see cref="CloseAsync"/>.
    /// </summary>
    IAsyncEnumerable<TranscriptionEvent> Events { get; }
    /// <summary>
    /// All <c>IsFinal</c> segments observed so far, in arrival order. Survives
    /// reconnects.
    /// </summary>
    IReadOnlyList<LiveTranscriptSegment> CollectedSegments { get; }

    Task OpenAsync(CancellationToken ct);
    /// <summary>
    /// Push a 16-bit signed PCM chunk to the provider.
    /// </summary>
    Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct);
    /// <summary>
    /// Tell the provider to finalize the current audio buffer.
    /// </summary>
    Task EndTurnAsync();
    Task CloseAsync(TimeSpan timeout);
}
