namespace WaiComputer.Core.Audio;

/// <summary>
/// Fixed-capacity ring of int16 PCM bytes that keeps the most recent N samples
/// (e.g. 500 ms / 8000 samples of dictation pre-roll). Append-only; oldest bytes
/// are evicted once full. <see cref="Snapshot"/> returns the buffered audio
/// oldest-first. Not thread-safe — the owner serialises access.
/// </summary>
public sealed class PcmRingBuffer
{
    private readonly byte[] _buffer;
    private int _start; // index of the oldest byte
    private int _count; // bytes currently held

    public PcmRingBuffer(int capacitySamples)
    {
        if (capacitySamples < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(capacitySamples), capacitySamples, "Capacity must be >= 1 sample.");
        }
        _buffer = new byte[capacitySamples * 2];
    }

    public int CapacityBytes => _buffer.Length;

    public int CountBytes => _count;

    public void Append(ReadOnlySpan<byte> pcm16)
    {
        if (pcm16.IsEmpty)
        {
            return;
        }

        // A chunk at/over capacity simply becomes the whole buffer (its tail).
        if (pcm16.Length >= _buffer.Length)
        {
            pcm16[^_buffer.Length..].CopyTo(_buffer);
            _start = 0;
            _count = _buffer.Length;
            return;
        }

        foreach (var b in pcm16)
        {
            if (_count == _buffer.Length)
            {
                _buffer[_start] = b;                       // overwrite oldest
                _start = (_start + 1) % _buffer.Length;    // advance the window
            }
            else
            {
                _buffer[(_start + _count) % _buffer.Length] = b;
                _count++;
            }
        }
    }

    public byte[] Snapshot()
    {
        var result = new byte[_count];
        for (var i = 0; i < _count; i++)
        {
            result[i] = _buffer[(_start + i) % _buffer.Length];
        }
        return result;
    }

    public void Clear()
    {
        _start = 0;
        _count = 0;
    }
}
