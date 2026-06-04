using System.Buffers.Binary;
using FluentAssertions;
using WaiComputer.Core.Audio;
using Xunit;

namespace WaiComputer.Core.Tests.Audio;

public class AudioFileWriterTests
{
    [Fact]
    public async Task HeaderHasCorrectMagicAndFmtBlock()
    {
        var ms = new MemoryStream();
        await using (var writer = new AudioFileWriter(ms, 16000, 1, ownsStream: false))
        {
            writer.Complete();
        }
        ms.Position = 0;
        var buf = ms.ToArray();
        buf.AsSpan(0, 4).ToArray().Should().Equal((byte)'R', (byte)'I', (byte)'F', (byte)'F');
        buf.AsSpan(8, 4).ToArray().Should().Equal((byte)'W', (byte)'A', (byte)'V', (byte)'E');
        buf.AsSpan(12, 4).ToArray().Should().Equal((byte)'f', (byte)'m', (byte)'t', (byte)' ');
        buf.AsSpan(36, 4).ToArray().Should().Equal((byte)'d', (byte)'a', (byte)'t', (byte)'a');
        BinaryPrimitives.ReadUInt16LittleEndian(buf.AsSpan(20, 2)).Should().Be(1);     // PCM
        BinaryPrimitives.ReadUInt16LittleEndian(buf.AsSpan(22, 2)).Should().Be(1);     // mono
        BinaryPrimitives.ReadUInt32LittleEndian(buf.AsSpan(24, 4)).Should().Be(16000); // sample rate
        BinaryPrimitives.ReadUInt16LittleEndian(buf.AsSpan(34, 2)).Should().Be(16);    // bits/sample
    }

    [Fact]
    public async Task RiffAndDataSizesPatchedOnFinalize()
    {
        var ms = new MemoryStream();
        var pcm = new byte[32000]; // 1 second of 16 kHz mono int16 silence
        await using (var writer = new AudioFileWriter(ms, 16000, 1, ownsStream: false))
        {
            writer.WriteEncodedPcm(pcm);
            writer.Complete();
        }
        var buf = ms.ToArray();
        BinaryPrimitives.ReadUInt32LittleEndian(buf.AsSpan(4, 4)).Should().Be(36u + 32000u);
        BinaryPrimitives.ReadUInt32LittleEndian(buf.AsSpan(40, 4)).Should().Be(32000u);
    }

    [Fact]
    public void DurationCalcMatchesByteCount()
    {
        using var ms = new MemoryStream();
        var writer = new AudioFileWriter(ms, 16000, 1, ownsStream: false);
        writer.WriteEncodedPcm(new byte[32000]);
        writer.DurationSeconds.Should().BeApproximately(1.0, 1e-6);
    }

    [Fact]
    public void StereoDurationHalvesSinceTwoChannels()
    {
        using var ms = new MemoryStream();
        var writer = new AudioFileWriter(ms, 16000, 2, ownsStream: false);
        writer.WriteEncodedPcm(new byte[64000]); // 1 s of 16 kHz stereo int16
        writer.DurationSeconds.Should().BeApproximately(1.0, 1e-6);
    }

    [Fact]
    public void RejectsWritesAfterFinalize()
    {
        using var ms = new MemoryStream();
        var writer = new AudioFileWriter(ms, 16000, 1, ownsStream: false);
        writer.Complete();
        Action act = () => writer.WriteEncodedPcm(new byte[2]);
        act.Should().Throw<InvalidOperationException>();
    }

    [Fact]
    public async Task IncrementalWritesAccumulate()
    {
        var ms = new MemoryStream();
        await using var writer = new AudioFileWriter(ms, 16000, 1, ownsStream: false);
        writer.WriteEncodedPcm(new byte[100]);
        writer.WriteEncodedPcm(new byte[200]);
        writer.WriteEncodedPcm(new byte[300]);
        writer.BytesWritten.Should().Be(600);
    }
}
