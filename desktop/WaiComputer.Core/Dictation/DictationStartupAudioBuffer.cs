namespace WaiComputer.Core.Dictation;

/// <summary>Thrown when buffered pre-roll audio exceeds the configured ceiling (no-fallback).</summary>
public sealed class DictationStartupAudioBufferException : Exception
{
    public DictationStartupAudioBufferException(int bytes, int limit)
        : base($"Dictation startup buffer overflow: {bytes} > {limit} bytes.") { }
}

/// <summary>Outcome of appending a chunk to the startup buffer.</summary>
public readonly record struct DictationAppendResult(bool WasSent, int BufferedChunks, int BufferedBytes)
{
    public static DictationAppendResult Buffered(int chunks, int bytes) => new(false, chunks, bytes);
    public static DictationAppendResult Sent() => new(true, 0, 0);
}

/// <summary>
/// Holds the pre-roll + early PCM chunks captured before the realtime provider
/// is connected, then flushes them in order once streaming starts and switches
/// to pass-through. Ports the macOS <c>DictationStartupAudioBuffer</c>:
/// capacity-limited (overflow throws — no silent drop), and serialised so an
/// append can't race the start-streaming flush.
/// </summary>
public sealed class DictationStartupAudioBuffer
{
    private readonly int _maxBufferedBytes;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly List<byte[]> _buffered = new();
    private int _bufferedBytes;
    private Func<ReadOnlyMemory<byte>, CancellationToken, Task>? _send;

    public DictationStartupAudioBuffer(int maxBufferedBytes) => _maxBufferedBytes = Math.Max(1, maxBufferedBytes);

    /// <summary>
    /// Append a chunk. Before streaming starts the chunk is buffered (throws if
    /// that would exceed the ceiling); once streaming is live it is sent straight
    /// through to the provider.
    /// </summary>
    public async Task<DictationAppendResult> AppendAsync(ReadOnlyMemory<byte> data, CancellationToken ct)
    {
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (data.IsEmpty)
            {
                return DictationAppendResult.Buffered(_buffered.Count, _bufferedBytes);
            }

            if (_send is { } send)
            {
                await send(data, ct).ConfigureAwait(false);
                return DictationAppendResult.Sent();
            }

            var next = _bufferedBytes + data.Length;
            if (next > _maxBufferedBytes)
            {
                throw new DictationStartupAudioBufferException(next, _maxBufferedBytes);
            }

            _buffered.Add(data.ToArray());
            _bufferedBytes = next;
            return DictationAppendResult.Buffered(_buffered.Count, _bufferedBytes);
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <summary>
    /// Begin streaming: flush the buffered chunks to <paramref name="send"/> in
    /// capture order, then switch to pass-through. Returns the number of chunks
    /// flushed.
    /// </summary>
    public async Task<int> StartStreamingAsync(Func<ReadOnlyMemory<byte>, CancellationToken, Task> send, CancellationToken ct)
    {
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var count = _buffered.Count;
            foreach (var chunk in _buffered)
            {
                await send(chunk, ct).ConfigureAwait(false);
            }
            _buffered.Clear();
            _bufferedBytes = 0;
            _send = send;
            return count;
        }
        finally
        {
            _gate.Release();
        }
    }
}
