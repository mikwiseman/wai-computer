namespace WaiComputer.Core.Audio;

/// <summary>
/// A single-source int16 PCM accumulator — the .NET analogue of the macOS
/// <c>micBuffer</c>/<c>systemBuffer</c> Float arrays with their
/// <c>prefix</c>/<c>removeFirst</c> dance. <see cref="TakeInto"/> drains what it
/// has and zero-pads the remainder, so the dual mixer can request an exact frame
/// count without the system source ever blocking the mic. Not thread-safe — the
/// owner serialises access.
/// </summary>
internal sealed class AudioSourceBuffer
{
    private readonly List<byte> _bytes = new();

    public int CountSamples => _bytes.Count / 2;

    public void Append(ReadOnlySpan<byte> pcm16)
    {
        if (!pcm16.IsEmpty)
        {
            _bytes.AddRange(pcm16);
        }
    }

    /// <summary>
    /// Copy <paramref name="samples"/> int16 samples into <paramref name="dst"/>
    /// (length must be <c>samples * 2</c>). If fewer are buffered, the rest is
    /// zero-padded (silence). Drains exactly the bytes that were available.
    /// </summary>
    public void TakeInto(int samples, Span<byte> dst)
    {
        var wantBytes = samples * 2;
        if (dst.Length != wantBytes)
        {
            throw new ArgumentException($"Destination must be {wantBytes} bytes for {samples} samples.", nameof(dst));
        }

        var have = Math.Min(_bytes.Count, wantBytes);
        for (var i = 0; i < have; i++)
        {
            dst[i] = _bytes[i];
        }
        for (var i = have; i < wantBytes; i++)
        {
            dst[i] = 0; // pad with silence
        }
        _bytes.RemoveRange(0, have);
    }

    public void Clear() => _bytes.Clear();
}
