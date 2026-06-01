using System;
using System.Buffers.Binary;
using FluentAssertions;
using WaiComputer.Core.Audio;
using Xunit;

namespace WaiComputer.Core.Tests.Audio;

public class AudioSourceBufferTests
{
    private static byte[] Pcm(params short[] s)
    {
        var b = new byte[s.Length * 2];
        for (var i = 0; i < s.Length; i++)
        {
            BinaryPrimitives.WriteInt16LittleEndian(b.AsSpan(i * 2, 2), s[i]);
        }
        return b;
    }

    private static short[] AsShorts(ReadOnlySpan<byte> b)
    {
        var s = new short[b.Length / 2];
        for (var i = 0; i < s.Length; i++)
        {
            s[i] = BinaryPrimitives.ReadInt16LittleEndian(b.Slice(i * 2, 2));
        }
        return s;
    }

    [Fact]
    public void AppendTracksSampleCount()
    {
        var buf = new AudioSourceBuffer();
        buf.Append(Pcm(1, 2, 3));
        buf.CountSamples.Should().Be(3);
    }

    [Fact]
    public void TakeIntoDrainsExactlyWhatWasRequested()
    {
        var buf = new AudioSourceBuffer();
        buf.Append(Pcm(1, 2, 3, 4));
        var dst = new byte[2 * 2];
        buf.TakeInto(2, dst);
        AsShorts(dst).Should().Equal((short)1, (short)2);
        buf.CountSamples.Should().Be(2);
    }

    [Fact]
    public void TakeIntoPadsWithSilenceWhenShort()
    {
        var buf = new AudioSourceBuffer();
        buf.Append(Pcm(5)); // only one sample available
        var dst = new byte[3 * 2];
        buf.TakeInto(3, dst);
        AsShorts(dst).Should().Equal((short)5, (short)0, (short)0);
        buf.CountSamples.Should().Be(0); // drained what it had
    }

    [Fact]
    public void ClearEmptiesBuffer()
    {
        var buf = new AudioSourceBuffer();
        buf.Append(Pcm(1, 2));
        buf.Clear();
        buf.CountSamples.Should().Be(0);
    }
}
