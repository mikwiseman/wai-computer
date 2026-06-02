using System;
using System.Buffers.Binary;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Audio;
using Xunit;

namespace WaiComputer.Core.Tests.Audio;

public class DualAudioCaptureTests
{
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

    [Fact]
    public async Task MixesMicAndSystemOnFlush()
    {
        var mic = new FakeCapture { Source = AudioSource.Microphone, HasReceivedAudio = true };
        var sys = new FakeCapture { Source = AudioSource.SystemAudio, HasReceivedAudio = true, LastAudibleAt = DateTimeOffset.UtcNow };
        var clock = new ManualFlushClock();
        var config = new AudioCaptureConfig(SampleRate: 1000, MixToMono: true, SeparateChannels: false);
        await using var cap = new DualAudioCapture(mic, sys, config, flushClock: clock);
        await cap.StartAsync(CancellationToken.None);

        mic.Push(Samples(100, 1000), 100);
        sys.Push(Samples(100, 500), 100);
        // Ensure BOTH sources are buffered before the single flush (the manual
        // clock means no flush fires until we tick) — otherwise a mic-only flush
        // would mix mic with silence.
        await WaitConsumed(mic);
        await WaitConsumed(sys);
        clock.Tick();

        var frame = await ReadOneFrame(cap);
        AsShorts(frame.Pcm16).Should().AllBeEquivalentTo((short)750); // (1000 + 500) / 2
        await cap.StopAsync();
    }

    [Fact]
    public async Task MicOnlyEmitsVerbatim()
    {
        var mic = new FakeCapture { Source = AudioSource.Microphone, HasReceivedAudio = true };
        var clock = new ManualFlushClock();
        var config = new AudioCaptureConfig(SampleRate: 1000);
        await using var cap = new DualAudioCapture(mic, null, config, flushClock: clock);
        await cap.StartAsync(CancellationToken.None);

        mic.Push(Samples(100, 1234), 100);
        await WaitConsumed(mic);
        clock.Tick();

        var frame = await ReadOneFrame(cap);
        AsShorts(frame.Pcm16).Should().AllBeEquivalentTo((short)1234);
        await cap.StopAsync();
    }

    // Waits until the read pump drains the pushed frame from the source channel
    // and appends it into the mixer (the settle covers the read-then-append
    // window), so a subsequent single flush sees a known, complete buffer.
    private static async Task WaitConsumed(FakeCapture cap, int timeoutMs = 2000)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            if (cap.Queued == 0)
            {
                await Task.Delay(20);
                return;
            }
            await Task.Delay(5);
        }
        throw new TimeoutException("Source frame was not consumed in time.");
    }

    private static async Task<AudioFrame> ReadOneFrame(DualAudioCapture cap, int timeoutMs = 2000)
    {
        using var cts = new CancellationTokenSource(timeoutMs);
        if (await cap.Frames.WaitToReadAsync(cts.Token) && cap.Frames.TryRead(out var frame))
        {
            return frame;
        }
        throw new TimeoutException("No audio frame produced.");
    }

    private sealed class FakeCapture : IMicrophoneCapture, ISystemAudioCapture
    {
        private readonly Channel<AudioFrame> _frames = Channel.CreateUnbounded<AudioFrame>();
        public AudioSource Source { get; init; }
        public bool IsCapturing { get; private set; }
        public bool HasReceivedAudio { get; set; }
        public DateTimeOffset? LastAudibleAt { get; set; }
        public ChannelReader<AudioFrame> Frames => _frames.Reader;
        public int Queued => _frames.Reader.Count;
        public Task StartAsync(CancellationToken ct) { IsCapturing = true; return Task.CompletedTask; }
        public Task StopAsync() { IsCapturing = false; _frames.Writer.TryComplete(); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { _frames.Writer.TryComplete(); return ValueTask.CompletedTask; }
        public void Push(byte[] pcm16, int samples) => _frames.Writer.TryWrite(new AudioFrame(pcm16, TimeSpan.Zero, samples));
    }

    private sealed class ManualFlushClock : IFlushClock
    {
        private readonly Channel<DateTimeOffset> _ticks = Channel.CreateUnbounded<DateTimeOffset>();
        public void Tick() => _ticks.Writer.TryWrite(DateTimeOffset.UnixEpoch);
        public IAsyncEnumerable<DateTimeOffset> Ticks(CancellationToken ct) => _ticks.Reader.ReadAllAsync(ct);
    }
}
