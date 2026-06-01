using System.Buffers.Binary;
using FluentAssertions;
using WaiComputer.Core.Audio;
using Xunit;

namespace WaiComputer.Core.Tests.Audio;

public class AudioMixerTests
{
    private static byte[] Pcm(params short[] samples)
    {
        var bytes = new byte[samples.Length * 2];
        for (int i = 0; i < samples.Length; i++)
        {
            BinaryPrimitives.WriteInt16LittleEndian(bytes.AsSpan(i * 2, 2), samples[i]);
        }
        return bytes;
    }

    private static short[] AsShorts(ReadOnlySpan<byte> bytes)
    {
        var s = new short[bytes.Length / 2];
        for (int i = 0; i < s.Length; i++)
        {
            s[i] = BinaryPrimitives.ReadInt16LittleEndian(bytes.Slice(i * 2, 2));
        }
        return s;
    }

    [Fact]
    public void MixToMonoSumsSamples()
    {
        var a = Pcm(100, 200, 300);
        var b = Pcm(50, 60, 70);
        var dst = new byte[a.Length];
        AudioMixer.MixToMono(a, b, dst);
        AsShorts(dst).Should().Equal((short)150, (short)260, (short)370);
    }

    [Fact]
    public void MixToMonoClipsAtMaxAndMin()
    {
        var a = Pcm(30000, -30000);
        var b = Pcm(20000, -20000);
        var dst = new byte[a.Length];
        AudioMixer.MixToMono(a, b, dst);
        AsShorts(dst).Should().Equal(short.MaxValue, short.MinValue);
    }

    [Fact]
    public void MixToMonoMismatchedLengthThrows()
    {
        var a = Pcm(1);
        var b = Pcm(1, 2);
        Action act = () => AudioMixer.MixToMono(a, b, new byte[a.Length]);
        act.Should().Throw<ArgumentException>();
    }

    [Fact]
    public void MixToMonoAverageAveragesSamples()
    {
        var a = Pcm(100, 200, 300);
        var b = Pcm(50, 60, 70);
        var dst = new byte[a.Length];
        AudioMixer.MixToMonoAverage(a, b, dst);
        AsShorts(dst).Should().Equal((short)75, (short)130, (short)185);
    }

    [Fact]
    public void MixToMonoAverageNeverClips()
    {
        var a = Pcm(30000, -30000);
        var b = Pcm(20000, -20000);
        var dst = new byte[a.Length];
        AudioMixer.MixToMonoAverage(a, b, dst);
        AsShorts(dst).Should().Equal((short)25000, (short)-25000); // averaged, not saturated
    }

    [Fact]
    public void InterleaveStereoPutsLeftAndRightInOrder()
    {
        var l = Pcm(100, 200);
        var r = Pcm(-100, -200);
        var dst = new byte[l.Length * 2];
        AudioMixer.InterleaveStereo(l, r, dst);
        AsShorts(dst).Should().Equal((short)100, (short)-100, (short)200, (short)-200);
    }

    [Fact]
    public void ThresholdDetection()
    {
        AudioMixer.ExceedsThreshold(Pcm(0, 0, 0), 32).Should().BeFalse();
        AudioMixer.ExceedsThreshold(Pcm(0, 100, 0), 32).Should().BeTrue();
        AudioMixer.ExceedsThreshold(Pcm(-50, 0, 0), 32).Should().BeTrue();
    }
}
