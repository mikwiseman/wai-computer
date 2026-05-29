using System.Buffers.Binary;
using Concentus;
using Concentus.Enums;
using Concentus.Oggfile;

namespace WaiComputer.Core.Audio;

/// <summary>Result of compressing a recording before upload.</summary>
public sealed record CompressedAudio(string Path, long ByteCount, double DurationSeconds);

/// <summary>
/// Transcodes the finalized PCM WAV recording to Ogg-Opus before upload. Raw
/// 16 kHz mono PCM is ~110 MB/hour and trips the 200 MB upload ceiling for
/// recordings over ~1h49m; Opus at speech bitrates is ~11 MB/hour. Pure-managed
/// (Concentus), so it runs identically on Windows and Linux.
/// </summary>
public static class AudioCompressor
{
    // Opus only accepts these input sample rates.
    private static readonly int[] SupportedSampleRates = { 8000, 12000, 16000, 24000, 48000 };

    /// <summary>
    /// Transcodes a PCM WAV file to Ogg-Opus, preserving sample rate and channel
    /// count. Streams the source so multi-hour recordings don't load fully into
    /// memory. Overwrites <paramref name="destOpusPath"/> if present.
    /// </summary>
    /// <param name="sourceWavPath">Path to the source PCM WAV file.</param>
    /// <param name="destOpusPath">Path to write the Ogg-Opus file to.</param>
    /// <param name="bitRate">Target Opus bitrate. 24 kbps mono is clean for
    /// speech and keeps a 4-hour meeting near ~45 MB.</param>
    public static CompressedAudio CompressWavToOpus(
        string sourceWavPath,
        string destOpusPath,
        int bitRate = 24_000)
    {
        using var input = new FileStream(sourceWavPath, FileMode.Open, FileAccess.Read);
        var (sampleRate, channels, dataLength) = ReadWavHeader(input);

        if (Array.IndexOf(SupportedSampleRates, (int)sampleRate) < 0)
        {
            throw new NotSupportedException($"Opus does not support {sampleRate} Hz input.");
        }
        if (dataLength <= 0)
        {
            throw new InvalidDataException("WAV contains no PCM data.");
        }

        var encoder = OpusCodecFactory.CreateEncoder((int)sampleRate, channels, OpusApplication.OPUS_APPLICATION_VOIP);
        encoder.Bitrate = bitRate;

        long totalFrames = dataLength / (2L * channels);

        using (var output = new FileStream(destOpusPath, FileMode.Create, FileAccess.Write))
        {
            var oggOut = new OpusOggWriteStream(encoder, output, null, (int)sampleRate);

            const int frameChunk = 16_384;
            var byteBuffer = new byte[frameChunk * channels * 2];
            var sampleBuffer = new short[frameChunk * channels];
            long remaining = dataLength;

            while (remaining > 0)
            {
                int toRead = (int)Math.Min(byteBuffer.Length, remaining);
                int read = input.ReadAtLeast(byteBuffer.AsSpan(0, toRead), toRead, throwOnEndOfStream: false);
                if (read <= 0) break;

                int sampleCount = read / 2;
                for (int i = 0; i < sampleCount; i++)
                {
                    sampleBuffer[i] = BinaryPrimitives.ReadInt16LittleEndian(byteBuffer.AsSpan(i * 2, 2));
                }
                oggOut.WriteSamples(sampleBuffer, 0, sampleCount);
                remaining -= read;
            }

            oggOut.Finish();
        }

        var byteCount = new FileInfo(destOpusPath).Length;
        var durationSeconds = (double)totalFrames / sampleRate;
        return new CompressedAudio(destOpusPath, byteCount, durationSeconds);
    }

    /// <summary>
    /// Walks RIFF chunks to read format + locate PCM data, leaving the stream
    /// positioned at the first PCM byte. Tolerates extra chunks (LIST/fact/etc.).
    /// </summary>
    private static (uint sampleRate, int channels, long dataLength) ReadWavHeader(Stream stream)
    {
        Span<byte> tag = stackalloc byte[4];
        Span<byte> u32 = stackalloc byte[4];

        stream.ReadExactly(tag);
        if (!tag.SequenceEqual("RIFF"u8)) throw new InvalidDataException("Not a RIFF file.");
        stream.ReadExactly(u32); // overall RIFF size (ignored)
        stream.ReadExactly(tag);
        if (!tag.SequenceEqual("WAVE"u8)) throw new InvalidDataException("Not a WAVE file.");

        uint sampleRate = 0;
        ushort channels = 0;
        var haveFormat = false;

        while (true)
        {
            stream.ReadExactly(tag);
            stream.ReadExactly(u32);
            uint chunkSize = BinaryPrimitives.ReadUInt32LittleEndian(u32);

            if (tag.SequenceEqual("fmt "u8))
            {
                Span<byte> fmt = stackalloc byte[16];
                stream.ReadExactly(fmt);
                channels = BinaryPrimitives.ReadUInt16LittleEndian(fmt[2..4]);
                sampleRate = BinaryPrimitives.ReadUInt32LittleEndian(fmt[4..8]);
                haveFormat = true;

                long skip = (long)chunkSize - 16 + (chunkSize & 1); // remainder + padding byte
                if (skip > 0) stream.Seek(skip, SeekOrigin.Current);
            }
            else if (tag.SequenceEqual("data"u8))
            {
                if (!haveFormat) throw new InvalidDataException("WAV 'data' chunk preceded 'fmt '.");
                if (channels < 1) throw new InvalidDataException("WAV has no channels.");
                return (sampleRate, channels, chunkSize);
            }
            else
            {
                stream.Seek(chunkSize + (chunkSize & 1), SeekOrigin.Current);
            }
        }
    }
}
