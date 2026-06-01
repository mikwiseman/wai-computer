using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Dictation;
using Xunit;

namespace WaiComputer.Core.Tests.Dictation;

public class DictationStartupAudioBufferTests
{
    private static byte[] B(byte fill, int n)
    {
        var b = new byte[n];
        Array.Fill(b, fill);
        return b;
    }

    [Fact]
    public async Task BuffersThenFlushesInOrderThenPassesThrough()
    {
        var buf = new DictationStartupAudioBuffer(100_000);
        (await buf.AppendAsync(B(1, 10), CancellationToken.None)).WasSent.Should().BeFalse();
        (await buf.AppendAsync(B(2, 10), CancellationToken.None)).WasSent.Should().BeFalse();

        var sent = new List<byte[]>();
        Task Sink(ReadOnlyMemory<byte> d, CancellationToken c) { sent.Add(d.ToArray()); return Task.CompletedTask; }

        var flushed = await buf.StartStreamingAsync(Sink, CancellationToken.None);

        flushed.Should().Be(2);
        sent.Should().HaveCount(2);
        sent[0][0].Should().Be(1);
        sent[1][0].Should().Be(2); // capture order preserved

        (await buf.AppendAsync(B(3, 10), CancellationToken.None)).WasSent.Should().BeTrue(); // now pass-through
        sent.Should().HaveCount(3);
        sent[2][0].Should().Be(3);
    }

    [Fact]
    public async Task OverflowThrows()
    {
        var buf = new DictationStartupAudioBuffer(15);
        await buf.AppendAsync(B(1, 10), CancellationToken.None);

        var act = async () => await buf.AppendAsync(B(2, 10), CancellationToken.None);

        await act.Should().ThrowAsync<DictationStartupAudioBufferException>();
    }
}
