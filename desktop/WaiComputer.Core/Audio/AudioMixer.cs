using System.Buffers.Binary;

namespace WaiComputer.Core.Audio;

/// <summary>
/// Pure-CPU helpers used by <c>DualAudioCapture</c> to combine microphone +
/// system-audio frames into a single mono stream (sum-with-clip) or into a
/// 2-channel interleaved buffer (mic=left, system=right). The math here is
/// platform-neutral and easy to unit-test on Mac.
/// </summary>
public static class AudioMixer
{
    /// <summary>
    /// Sum two equal-length int16 mono buffers with saturation (clip to
    /// <see cref="short.MinValue"/> / <see cref="short.MaxValue"/>). Output
    /// is written into <paramref name="destination"/>.
    /// </summary>
    public static void MixToMono(ReadOnlySpan<byte> a, ReadOnlySpan<byte> b, Span<byte> destination)
    {
        if (a.Length != b.Length || a.Length != destination.Length)
        {
            throw new ArgumentException("All three buffers must have equal length.");
        }
        if ((a.Length & 1) != 0)
        {
            throw new ArgumentException("Buffers must contain a whole number of int16 samples.");
        }

        for (int i = 0; i < a.Length; i += 2)
        {
            int sa = BinaryPrimitives.ReadInt16LittleEndian(a.Slice(i, 2));
            int sb = BinaryPrimitives.ReadInt16LittleEndian(b.Slice(i, 2));
            int sum = sa + sb;
            if (sum > short.MaxValue) sum = short.MaxValue;
            else if (sum < short.MinValue) sum = short.MinValue;
            BinaryPrimitives.WriteInt16LittleEndian(destination.Slice(i, 2), (short)sum);
        }
    }

    /// <summary>
    /// Interleave mic (left) and system (right) into a 2-channel int16 buffer.
    /// Output length is exactly twice the input length.
    /// </summary>
    public static void InterleaveStereo(ReadOnlySpan<byte> left, ReadOnlySpan<byte> right, Span<byte> destination)
    {
        if (left.Length != right.Length)
        {
            throw new ArgumentException("Mic and system buffers must be equal length.");
        }
        if (destination.Length != left.Length * 2)
        {
            throw new ArgumentException("Destination must be 2× input length.");
        }
        if ((left.Length & 1) != 0)
        {
            throw new ArgumentException("Buffers must contain a whole number of int16 samples.");
        }

        int o = 0;
        for (int i = 0; i < left.Length; i += 2)
        {
            destination[o++] = left[i];
            destination[o++] = left[i + 1];
            destination[o++] = right[i];
            destination[o++] = right[i + 1];
        }
    }

    /// <summary>
    /// Check whether any sample in <paramref name="pcm"/> exceeds the absolute
    /// audibility threshold. Used by stall detection.
    /// </summary>
    public static bool ExceedsThreshold(ReadOnlySpan<byte> pcm, short threshold)
    {
        if ((pcm.Length & 1) != 0) return false;
        for (int i = 0; i < pcm.Length; i += 2)
        {
            var v = BinaryPrimitives.ReadInt16LittleEndian(pcm.Slice(i, 2));
            if (v >= threshold || -v >= threshold) return true;
        }
        return false;
    }
}
