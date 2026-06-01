namespace WaiComputer.Core.Realtime;

/// <summary>
/// Re-frames a linear16 PCM byte stream into the provider's accepted frame
/// window (20 ms minimum .. 1 s maximum), porting the macOS <c>pcmAudioChunks</c>
/// logic. Sub-minimum residue is held between <see cref="Push"/> calls; on a
/// forced flush the remainder is zero-padded up to the 20 ms minimum. Not
/// thread-safe — drive from a single producer.
/// </summary>
internal sealed class PcmRechunker
{
    private readonly int _minChunkBytes;
    private readonly int _maxChunkBytes;
    private readonly List<byte> _pending = new();

    public PcmRechunker(int sampleRate, int channels)
    {
        var bytesPerSecond = Math.Max(1, sampleRate) * Math.Max(1, channels) * 2;
        _minChunkBytes = Math.Max(1, bytesPerSecond * 20 / 1000);
        _maxChunkBytes = bytesPerSecond;
    }

    public int MinChunkBytes => _minChunkBytes;

    public int MaxChunkBytes => _maxChunkBytes;

    /// <summary>
    /// Append <paramref name="input"/> and return the chunks that are now ready.
    /// While the buffer holds a full second it is split into 1 s chunks. With
    /// <paramref name="forceFlush"/> any remainder is emitted too — zero-padded
    /// up to the minimum when it is shorter; otherwise sub-minimum residue is
    /// retained for the next call.
    /// </summary>
    public IReadOnlyList<byte[]> Push(ReadOnlySpan<byte> input, bool forceFlush)
    {
        if (!input.IsEmpty)
        {
            _pending.AddRange(input);
        }

        var chunks = new List<byte[]>();

        while (_pending.Count >= _maxChunkBytes)
        {
            chunks.Add(TakeFront(_maxChunkBytes));
        }

        if (forceFlush)
        {
            if (_pending.Count > 0)
            {
                var size = Math.Max(_pending.Count, _minChunkBytes);
                var chunk = new byte[size];
                _pending.CopyTo(chunk); // copies _pending.Count bytes; the tail stays zero (pad)
                _pending.Clear();
                chunks.Add(chunk);
            }
        }
        else if (_pending.Count >= _minChunkBytes)
        {
            chunks.Add(TakeFront(_pending.Count));
        }

        return chunks;
    }

    private byte[] TakeFront(int count)
    {
        var chunk = new byte[count];
        _pending.CopyTo(0, chunk, 0, count);
        _pending.RemoveRange(0, count);
        return chunk;
    }
}
