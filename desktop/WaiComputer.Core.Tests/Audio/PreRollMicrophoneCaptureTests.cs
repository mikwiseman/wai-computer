using System;
using System.Diagnostics;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Audio;
using Xunit;

namespace WaiComputer.Core.Tests.Audio;

public class PreRollMicrophoneCaptureTests
{
    private static byte[] Samples(int n, byte fill)
    {
        var b = new byte[n * 2];
        Array.Fill(b, fill);
        return b;
    }

    [Fact]
    public async Task PreRollSnapshotsBufferedAudioThenStreamsLive()
    {
        var mic = new FakeMic();
        await using var cap = new PreRollMicrophoneCapture(mic, new AudioCaptureConfig(SampleRate: 1000)); // 500-sample ring
        await cap.PrewarmAsync(CancellationToken.None);

        mic.Push(Samples(100, 1));
        mic.Push(Samples(100, 2));
        await WaitConsumed(mic); // both buffered into the ring before the lease

        var lease = cap.Lease();
        lease.PreRoll.Should().ContainSingle();
        lease.PreRoll[0].SampleCount.Should().Be(200); // 100 + 100 captured pre-roll

        mic.Push(Samples(50, 3)); // post-lease -> live channel
        var live = await ReadOne(lease.Frames);
        live.SampleCount.Should().Be(50);

        await cap.TeardownAsync();
    }

    [Fact]
    public async Task EmptyPreRollWhenNothingBufferedBeforeLease()
    {
        var mic = new FakeMic();
        await using var cap = new PreRollMicrophoneCapture(mic, new AudioCaptureConfig(SampleRate: 1000));
        await cap.PrewarmAsync(CancellationToken.None);

        var lease = cap.Lease();

        lease.PreRoll.Should().BeEmpty();
        await cap.TeardownAsync();
    }

    [Fact]
    public async Task SecondLeaseThrows()
    {
        var mic = new FakeMic();
        await using var cap = new PreRollMicrophoneCapture(mic, new AudioCaptureConfig(SampleRate: 1000));
        await cap.PrewarmAsync(CancellationToken.None);
        cap.Lease();

        var act = () => cap.Lease();

        act.Should().Throw<InvalidOperationException>();
        await cap.TeardownAsync();
    }

    [Fact]
    public async Task PrewarmIsIdempotent()
    {
        var mic = new FakeMic();
        await using var cap = new PreRollMicrophoneCapture(mic, new AudioCaptureConfig(SampleRate: 1000));

        await cap.PrewarmAsync(CancellationToken.None);
        await cap.PrewarmAsync(CancellationToken.None); // second prewarm before teardown must be a no-op

        mic.StartCount.Should().Be(1); // mic started once, not twice (no orphaned pump/cts)
        await cap.TeardownAsync();
    }

    [Fact]
    public async Task IsReusableAcrossTurnsWithFreshPreRoll()
    {
        var mic = new FakeMic();
        await using var cap = new PreRollMicrophoneCapture(mic, new AudioCaptureConfig(SampleRate: 1000));

        // Turn 1.
        await cap.PrewarmAsync(CancellationToken.None);
        mic.Push(Samples(100, 1));
        await WaitConsumed(mic);
        cap.Lease().PreRoll[0].SampleCount.Should().Be(100);
        await cap.TeardownAsync();

        // Turn 2: re-lease must NOT throw, and the pre-roll must be fresh (turn-1 audio cleared).
        await cap.PrewarmAsync(CancellationToken.None);
        mic.Push(Samples(40, 2));
        await WaitConsumed(mic);

        var lease2 = cap.Lease();
        lease2.PreRoll.Should().ContainSingle();
        lease2.PreRoll[0].SampleCount.Should().Be(40); // only turn-2 audio, not 100 + 40
        mic.StartCount.Should().Be(2);
        await cap.TeardownAsync();
    }

    private static async Task WaitConsumed(FakeMic mic, int timeoutMs = 2000)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            if (mic.Queued == 0) { await Task.Delay(20); return; }
            await Task.Delay(5);
        }
        throw new TimeoutException("Mic frame not consumed in time.");
    }

    private static async Task<AudioFrame> ReadOne(ChannelReader<AudioFrame> reader, int timeoutMs = 2000)
    {
        using var cts = new CancellationTokenSource(timeoutMs);
        if (await reader.WaitToReadAsync(cts.Token) && reader.TryRead(out var frame))
        {
            return frame;
        }
        throw new TimeoutException("No live frame produced.");
    }

    private sealed class FakeMic : IMicrophoneCapture
    {
        private Channel<AudioFrame> _frames = Channel.CreateUnbounded<AudioFrame>();
        public AudioSource Source => AudioSource.Microphone;
        public bool IsCapturing { get; private set; }
        public bool HasReceivedAudio => false;
        public DateTimeOffset? LastAudibleAt => null;
        public int StartCount { get; private set; }
        public ChannelReader<AudioFrame> Frames => _frames.Reader;
        public int Queued => _frames.Reader.Count;
        public Task StartAsync(CancellationToken ct)
        {
            StartCount++;
            // Support stop -> start cycles (multi-turn dictation): re-open a fresh channel
            // once the previous one was completed by StopAsync.
            if (_frames.Reader.Completion.IsCompleted)
            {
                _frames = Channel.CreateUnbounded<AudioFrame>();
            }
            IsCapturing = true;
            return Task.CompletedTask;
        }
        public Task StopAsync() { IsCapturing = false; _frames.Writer.TryComplete(); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { _frames.Writer.TryComplete(); return ValueTask.CompletedTask; }
        public void Push(byte[] pcm16) => _frames.Writer.TryWrite(new AudioFrame(pcm16, TimeSpan.Zero, pcm16.Length / 2));
    }
}
