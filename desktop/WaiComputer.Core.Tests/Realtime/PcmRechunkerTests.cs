using System;
using System.Collections.Generic;
using System.Linq;
using FluentAssertions;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class PcmRechunkerTests
{
    // 16 kHz mono linear16: 32000 B/s -> min = 640 B (20 ms), max = 32000 B (1 s).
    private static PcmRechunker New() => new(16000, 1);

    private static byte[] Bytes(int n, byte fill = 1)
    {
        var b = new byte[n];
        Array.Fill(b, fill);
        return b;
    }

    [Fact]
    public void ExposesFrameWindowForSixteenKMono()
    {
        var r = New();
        r.MinChunkBytes.Should().Be(640);
        r.MaxChunkBytes.Should().Be(32_000);
    }

    [Fact]
    public void SubMinimumResidueIsHeld()
    {
        New().Push(Bytes(300), forceFlush: false).Should().BeEmpty();
    }

    [Fact]
    public void EmitsWhenReachingMinChunk()
    {
        New().Push(Bytes(640), forceFlush: false).Should().ContainSingle().Which.Length.Should().Be(640);
    }

    [Fact]
    public void SplitsAtOneSecondCeilingThenEmitsResidueAboveMin()
    {
        var chunks = New().Push(Bytes(80_000), forceFlush: false);
        chunks.Select(c => c.Length).Should().Equal(32_000, 32_000, 16_000);
    }

    [Fact]
    public void ForceFlushPadsRemainderWithZeros()
    {
        var chunk = New().Push(Bytes(100, fill: 7), forceFlush: true).Should().ContainSingle().Subject;
        chunk.Length.Should().Be(640);
        chunk.Take(100).Should().AllBeEquivalentTo((byte)7);
        chunk.Skip(100).Should().AllBeEquivalentTo((byte)0);
    }

    [Fact]
    public void ForceFlushEmptyPendingReturnsNothing()
    {
        New().Push(ReadOnlySpan<byte>.Empty, forceFlush: true).Should().BeEmpty();
    }

    [Fact]
    public void AccumulatesSubMinimumAcrossCallsThenEmits()
    {
        var r = New();
        r.Push(Bytes(300), forceFlush: false).Should().BeEmpty();          // held
        r.Push(Bytes(400), forceFlush: false)                              // 700 >= 640 -> emit
            .Should().ContainSingle().Which.Length.Should().Be(700);
    }

    [Fact]
    public void PreservesByteContentAndOrderAcrossCalls()
    {
        var r = New();
        var outBytes = new List<byte>();
        foreach (var c in r.Push(Bytes(320, fill: 9), false)) outBytes.AddRange(c); // held (320 < 640)
        foreach (var c in r.Push(Bytes(320, fill: 5), false)) outBytes.AddRange(c); // 640 -> emit
        outBytes.Should().HaveCount(640);
        outBytes.Take(320).Should().AllBeEquivalentTo((byte)9);
        outBytes.Skip(320).Should().AllBeEquivalentTo((byte)5);
    }
}
