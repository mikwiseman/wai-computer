using System;
using System.Buffers.Binary;
using FluentAssertions;
using WaiComputer.Core.Audio;
using Xunit;

namespace WaiComputer.Core.Tests.Audio;

public class BufferedDualMixerTests
{
    // SampleRate 1000 -> MinFlushSamples = 80, MaxStallPadSamples = 1000.
    private static AudioCaptureConfig Mono() => new(SampleRate: 1000, MixToMono: true, SeparateChannels: false);
    private static AudioCaptureConfig Stereo() => new(SampleRate: 1000, MixToMono: false, SeparateChannels: true);

    private static byte[] Samples(int n, short v)
    {
        var b = new byte[n * 2];
        for (var i = 0; i < n; i++)
        {
            BinaryPrimitives.WriteInt16LittleEndian(b.AsSpan(i * 2, 2), v);
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

    [Theory]
    [InlineData(50, 200, 0)]    // (d) mic below floor -> nothing
    [InlineData(100, 100, 100)] // (a) both ready -> min
    [InlineData(120, 90, 90)]   // (a) both >= floor -> min
    [InlineData(100, 0, 100)]   // (b) system stalled -> cap at maxStallPad (1000) -> 100
    [InlineData(2000, 0, 1000)] // (b) system stalled -> capped at 1000
    [InlineData(100, 40, 80)]   // (c) system partial -> min(mic, max(sys, floor)) = min(100, 80)
    [InlineData(60, 40, 0)]     // (d) mic below floor even with some system
    public void ComputeFramesPortsMacCases(int mic, int sys, int expected)
        => BufferedDualMixer.ComputeFrames(mic, sys, minFlush: 80, maxStallPad: 1000).Should().Be(expected);

    [Fact]
    public void NoFlushUntilMicReachesFloor()
    {
        var mixer = new BufferedDualMixer(Mono());
        mixer.AppendMic(Samples(50, 1000)); // < 80
        mixer.TryFlush(hasSystemSource: true, systemUsable: true).Should().BeNull();
    }

    [Fact]
    public void MixesMonoAverageWhenBothPresent()
    {
        var mixer = new BufferedDualMixer(Mono());
        mixer.AppendMic(Samples(100, 1000));
        mixer.AppendSystem(Samples(100, 500));

        var frame = mixer.TryFlush(hasSystemSource: true, systemUsable: true);

        frame.Should().NotBeNull();
        frame!.Value.SampleCount.Should().Be(100);
        AsShorts(frame.Value.Pcm16).Should().AllBeEquivalentTo((short)750); // (1000+500)/2
    }

    [Fact]
    public void MicVerbatimWhenSystemNotUsable()
    {
        var mixer = new BufferedDualMixer(Mono());
        mixer.AppendMic(Samples(100, 1000)); // no system samples; stalled

        var frame = mixer.TryFlush(hasSystemSource: true, systemUsable: false);

        frame.Should().NotBeNull();
        AsShorts(frame!.Value.Pcm16).Should().AllBeEquivalentTo((short)1000); // no attenuation
    }

    [Fact]
    public void MicOnlySourceEmitsVerbatim()
    {
        var mixer = new BufferedDualMixer(Mono());
        mixer.AppendMic(Samples(100, 1234));

        var frame = mixer.TryFlush(hasSystemSource: false, systemUsable: false);

        frame.Should().NotBeNull();
        AsShorts(frame!.Value.Pcm16).Should().AllBeEquivalentTo((short)1234);
    }

    [Fact]
    public void StereoInterleavesMicAndSystem()
    {
        var mixer = new BufferedDualMixer(Stereo());
        mixer.AppendMic(Samples(100, 1000));
        mixer.AppendSystem(Samples(100, 500));

        var frame = mixer.TryFlush(hasSystemSource: true, systemUsable: true);

        frame.Should().NotBeNull();
        frame!.Value.SampleCount.Should().Be(100);
        frame.Value.SizeBytes.Should().Be(400); // 100 frames * 2 channels * 2 bytes
        var shorts = AsShorts(frame.Value.Pcm16);
        shorts[0].Should().Be(1000); // mic (left)
        shorts[1].Should().Be(500);  // system (right)
    }

    [Fact]
    public void TimestampsAreSampleAccurateAcrossFlushes()
    {
        var mixer = new BufferedDualMixer(Mono());
        mixer.AppendMic(Samples(100, 1));
        var first = mixer.TryFlush(hasSystemSource: false, systemUsable: false);
        mixer.AppendMic(Samples(100, 1));
        var second = mixer.TryFlush(hasSystemSource: false, systemUsable: false);

        first!.Value.Timestamp.Should().Be(TimeSpan.Zero);
        second!.Value.Timestamp.Should().Be(TimeSpan.FromMilliseconds(100)); // 100 samples @ 1000 Hz
    }
}
