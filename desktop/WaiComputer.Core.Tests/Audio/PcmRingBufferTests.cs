using System;
using FluentAssertions;
using WaiComputer.Core.Audio;
using Xunit;

namespace WaiComputer.Core.Tests.Audio;

public class PcmRingBufferTests
{
    private static byte[] Bytes(int n, byte fill)
    {
        var b = new byte[n];
        Array.Fill(b, fill);
        return b;
    }

    [Fact]
    public void KeepsAppendedBytesUnderCapacity()
    {
        var ring = new PcmRingBuffer(capacitySamples: 100); // 200 bytes
        ring.Append(Bytes(40, 7));
        ring.CountBytes.Should().Be(40);
        ring.Snapshot().Should().HaveCount(40).And.AllBeEquivalentTo((byte)7);
    }

    [Fact]
    public void EvictsOldestWhenFull()
    {
        var ring = new PcmRingBuffer(capacitySamples: 4); // 8 bytes
        ring.Append(Bytes(8, 1)); // fills
        ring.Append(Bytes(4, 2)); // evicts the 4 oldest
        var snap = ring.Snapshot();
        snap.Should().HaveCount(8);
        snap[..4].Should().AllBeEquivalentTo((byte)1);
        snap[4..].Should().AllBeEquivalentTo((byte)2);
    }

    [Fact]
    public void OversizedAppendKeepsOnlyTail()
    {
        var ring = new PcmRingBuffer(capacitySamples: 4); // 8 bytes
        var big = new byte[20];
        for (var i = 0; i < big.Length; i++) big[i] = (byte)i;
        ring.Append(big);
        ring.Snapshot().Should().Equal(big[^8..]); // last 8 bytes only
    }

    [Fact]
    public void ClearEmptiesBuffer()
    {
        var ring = new PcmRingBuffer(capacitySamples: 4);
        ring.Append(Bytes(8, 1));
        ring.Clear();
        ring.CountBytes.Should().Be(0);
        ring.Snapshot().Should().BeEmpty();
    }
}
