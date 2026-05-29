using System.Buffers.Binary;
using Concentus;
using Concentus.Oggfile;
using FluentAssertions;
using WaiComputer.Core.Audio;
using Xunit;

namespace WaiComputer.Core.Tests.Audio;

public sealed class AudioCompressorTests : IDisposable
{
    private readonly string _dir;

    public AudioCompressorTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "AudioCompressorTests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_dir);
    }

    public void Dispose()
    {
        try { Directory.Delete(_dir, recursive: true); } catch { /* best effort */ }
    }

    private async Task<string> WriteSineWavAsync(
        string name,
        double seconds,
        uint sampleRate = 16000,
        ushort channels = 1,
        double frequency = 440)
    {
        var path = Path.Combine(_dir, name);
        var writer = new AudioFileWriter(path, sampleRate, channels);
        var frames = (int)(sampleRate * seconds);
        var pcm = new byte[frames * channels * 2];
        for (var n = 0; n < frames; n++)
        {
            var value = Math.Sin(2 * Math.PI * frequency * n / sampleRate);
            var sample = (short)(Math.Clamp(value, -1, 1) * 32767);
            for (var c = 0; c < channels; c++)
            {
                BinaryPrimitives.WriteInt16LittleEndian(pcm.AsSpan(((n * channels) + c) * 2, 2), sample);
            }
        }
        writer.WriteEncodedPcm(pcm);
        await writer.DisposeAsync();
        return path;
    }

    private static double DecodeOpusSeconds(string path, int sampleRate, int channels)
    {
        using var fs = File.OpenRead(path);
        var decoder = OpusCodecFactory.CreateDecoder(sampleRate, channels);
        var oggIn = new OpusOggReadStream(decoder, fs);
        long samples = 0;
        while (oggIn.HasNextPacket)
        {
            var packet = oggIn.DecodeNextPacket();
            if (packet != null)
            {
                samples += packet.Length; // interleaved across channels
            }
        }
        return (double)samples / channels / sampleRate;
    }

    [Fact]
    public async Task CompressMonoWav_ProducesSmallerDecodableOpus()
    {
        var source = await WriteSineWavAsync("source.wav", seconds: 3.0);
        var dest = Path.Combine(_dir, "out.opus");

        var result = AudioCompressor.CompressWavToOpus(source, dest, bitRate: 24_000);

        File.Exists(dest).Should().BeTrue();
        result.ByteCount.Should().Be(new FileInfo(dest).Length);
        new FileInfo(dest).Length.Should().BeLessThan(new FileInfo(source).Length,
            "Opus must be smaller than raw PCM WAV");
        result.DurationSeconds.Should().BeApproximately(3.0, 0.05);

        DecodeOpusSeconds(dest, 16000, 1).Should().BeApproximately(3.0, 0.3);
    }

    [Fact]
    public async Task CompressStereoWav_PreservesChannelCount()
    {
        var source = await WriteSineWavAsync("stereo.wav", seconds: 1.5, channels: 2);
        var dest = Path.Combine(_dir, "stereo.opus");

        var result = AudioCompressor.CompressWavToOpus(source, dest);

        result.ByteCount.Should().BeGreaterThan(0);
        DecodeOpusSeconds(dest, 16000, 2).Should().BeApproximately(1.5, 0.3);
    }

    [Fact]
    public async Task CompressOverwritesStaleDestination()
    {
        var source = await WriteSineWavAsync("source.wav", seconds: 1.0);
        var dest = Path.Combine(_dir, "out.opus");
        await File.WriteAllBytesAsync(dest, new byte[2048]); // junk

        var result = AudioCompressor.CompressWavToOpus(source, dest);

        DecodeOpusSeconds(dest, 16000, 1).Should().BeApproximately(1.0, 0.3);
        result.ByteCount.Should().Be(new FileInfo(dest).Length);
    }

    [Fact]
    public async Task UnsupportedSampleRate_Throws()
    {
        var source = await WriteSineWavAsync("cd.wav", seconds: 0.5, sampleRate: 44100);
        var act = () => AudioCompressor.CompressWavToOpus(source, Path.Combine(_dir, "cd.opus"));
        act.Should().Throw<NotSupportedException>();
    }
}
