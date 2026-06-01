using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Realtime;
using Xunit;

namespace WaiComputer.Core.Tests.Realtime;

public class ReconnectingRealtimeSessionTests
{
    private static RealtimeTranscriptionSessionConfig Cfg() => new(
        RealtimeProvider.Deepgram,
        Token: "tok",
        ExpiresInSeconds: 60,
        SampleRate: 16000,
        AudioFormat: "linear16",
        Language: "multi",
        Channels: 1,
        Model: "nova-3",
        KeepAliveIntervalSeconds: null,
        CommitStrategy: null,
        NoVerbatim: false,
        WebSocketUrl: "wss://wai.computer/api/transcription/stream",
        AuthScheme: AuthScheme.Bearer);

    private static ReconnectOptions Fast(int maxAttempts = 10) =>
        new(MaxAttempts: maxAttempts, BaseDelayMs: 0, MaxDelayMs: 0, MaxBufferChunks: 300);

    private static LiveTranscriptSegment Final(string text, long start, long end) =>
        new(text, Speaker: null, IsFinal: true, StartMs: start, EndMs: end, Confidence: 0.95);

    // ---- pure backoff -----------------------------------------------------

    [Fact]
    public void BaseBackoffIsExponentialAndCapped()
    {
        var o = new ReconnectOptions(BaseDelayMs: 500, MaxDelayMs: 30_000);
        ReconnectingRealtimeSession.BaseBackoffMs(1, o).Should().Be(500);
        ReconnectingRealtimeSession.BaseBackoffMs(2, o).Should().Be(1000);
        ReconnectingRealtimeSession.BaseBackoffMs(3, o).Should().Be(2000);
        ReconnectingRealtimeSession.BaseBackoffMs(7, o).Should().Be(30_000); // 500*64=32000 -> capped
        ReconnectingRealtimeSession.BaseBackoffMs(10, o).Should().Be(30_000);
    }

    // ---- reconnect behaviour ---------------------------------------------

    [Fact]
    public async Task ReconnectsOnTransientDropAndEmitsReconnected()
    {
        var fakes = new List<FakeRealtimeSession>();
        var remintCalls = 0;
        await using var session = new ReconnectingRealtimeSession(
            Cfg(), Factory(fakes), _ => { remintCalls++; return Task.FromResult(Cfg()); }, Fast());
        using var cts = new CancellationTokenSource();
        var collector = new EventCollector(session, cts.Token);

        await session.OpenAsync(CancellationToken.None);
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Connected>().Any());

        fakes[0].Drop();

        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Reconnected>().Any());
        collector.Snapshot().OfType<TranscriptionEvent.Reconnecting>().First().Attempt.Should().Be(1);
        remintCalls.Should().Be(1);
        fakes.Should().HaveCount(2);
        cts.Cancel();
    }

    [Fact]
    public async Task PreservesCollectedSegmentsAcrossReconnect()
    {
        var fakes = new List<FakeRealtimeSession>();
        await using var session = new ReconnectingRealtimeSession(
            Cfg(), Factory(fakes), _ => Task.FromResult(Cfg()), Fast());
        using var cts = new CancellationTokenSource();
        var collector = new EventCollector(session, cts.Token);

        await session.OpenAsync(CancellationToken.None);
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Connected>().Any());

        fakes[0].EmitTranscript(Final("hello world", 0, 900));
        fakes[0].Drop();
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Reconnected>().Any());

        fakes[1].EmitTranscript(Final("goodbye", 900, 1500));
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Transcript>().Any(t => t.Segment.Text == "goodbye"));

        session.CollectedSegments.Select(s => s.Text).Should().ContainInOrder("hello world", "goodbye");
        cts.Cancel();
    }

    [Fact]
    public async Task ExhaustsAttemptsThenEmitsReconnectionFailed()
    {
        var fakes = new List<FakeRealtimeSession>();
        await using var session = new ReconnectingRealtimeSession(
            Cfg(), Factory(fakes), _ => throw new InvalidOperationException("remint boom"), Fast(maxAttempts: 4));
        using var cts = new CancellationTokenSource();
        var collector = new EventCollector(session, cts.Token);

        await session.OpenAsync(CancellationToken.None);
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Connected>().Any());

        fakes[0].Drop();

        await collector.WaitFor(e => e.OfType<TranscriptionEvent.ReconnectionFailed>().Any());
        var snapshot = collector.Snapshot();
        snapshot.OfType<TranscriptionEvent.Reconnecting>().Should().HaveCount(4);
        snapshot.OfType<TranscriptionEvent.ReconnectionFailed>().Single().Cause.Should().NotBeNull();
        cts.Cancel();
    }

    [Fact]
    public async Task FatalProviderWarningStopsWithoutReconnect()
    {
        var fakes = new List<FakeRealtimeSession>();
        var remintCalls = 0;
        await using var session = new ReconnectingRealtimeSession(
            Cfg(), Factory(fakes), _ => { remintCalls++; return Task.FromResult(Cfg()); }, Fast());
        using var cts = new CancellationTokenSource();
        var collector = new EventCollector(session, cts.Token);

        await session.OpenAsync(CancellationToken.None);
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Connected>().Any());

        fakes[0].EmitWarning(TranscriptionErrorCodes.AuthError, "unauthorized");

        await collector.WaitFor(e => e.OfType<TranscriptionEvent.ProviderWarning>().Any());
        await Task.Delay(150); // settle: confirm no reconnect follows
        collector.Snapshot().OfType<TranscriptionEvent.Reconnecting>().Should().BeEmpty();
        remintCalls.Should().Be(0);
        cts.Cancel();
    }

    [Fact]
    public async Task EndTurnDisablesReconnect()
    {
        var fakes = new List<FakeRealtimeSession>();
        var remintCalls = 0;
        await using var session = new ReconnectingRealtimeSession(
            Cfg(), Factory(fakes), _ => { remintCalls++; return Task.FromResult(Cfg()); }, Fast());
        using var cts = new CancellationTokenSource();
        var collector = new EventCollector(session, cts.Token);

        await session.OpenAsync(CancellationToken.None);
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Connected>().Any());

        await session.EndTurnAsync();
        fakes[0].EndTurned.Should().BeTrue();

        fakes[0].Drop();
        await Task.Delay(150); // settle
        collector.Snapshot().OfType<TranscriptionEvent.Reconnecting>().Should().BeEmpty();
        remintCalls.Should().Be(0);
        cts.Cancel();
    }

    [Fact]
    public async Task SendPcmRechunksToOneSecondFrames()
    {
        var fakes = new List<FakeRealtimeSession>();
        await using var session = new ReconnectingRealtimeSession(
            Cfg(), Factory(fakes), _ => Task.FromResult(Cfg()), Fast());
        using var cts = new CancellationTokenSource();
        _ = new EventCollector(session, cts.Token);

        await session.OpenAsync(CancellationToken.None);
        await session.SendPcmAsync(new byte[64_000], CancellationToken.None); // 2 s -> two 1 s frames

        fakes[0].Sent.Should().HaveCount(2);
        fakes[0].Sent.Should().OnlyContain(c => c.Length == 32_000);
        cts.Cancel();
    }

    [Fact]
    public async Task BuffersAudioDuringReconnectAndReplaysInOrder()
    {
        var fakes = new List<FakeRealtimeSession>();
        var gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var remintCalls = 0;
        await using var session = new ReconnectingRealtimeSession(
            Cfg(),
            Factory(fakes),
            async _ => { if (Interlocked.Increment(ref remintCalls) == 1) { await gate.Task; } return Cfg(); },
            Fast());
        using var cts = new CancellationTokenSource();
        var collector = new EventCollector(session, cts.Token);

        await session.OpenAsync(CancellationToken.None);
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Connected>().Any());

        fakes[0].Drop();
        // Reconnect is now blocked inside remint -> session is in the reconnecting window.
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Reconnecting>().Any());

        await session.SendPcmAsync(new byte[32_000], CancellationToken.None); // buffered
        await session.SendPcmAsync(new byte[32_000], CancellationToken.None); // buffered

        gate.SetResult(); // let reconnect complete
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Reconnected>().Any());

        fakes[1].Sent.Should().HaveCount(2); // replayed in order on the new session
        cts.Cancel();
    }

    [Fact]
    public void RejectsInvalidReconnectOptions()
    {
        var act = () => new ReconnectingRealtimeSession(
            Cfg(), Factory(new List<FakeRealtimeSession>()), _ => Task.FromResult(Cfg()),
            new ReconnectOptions(MaxAttempts: 0));
        act.Should().Throw<ArgumentOutOfRangeException>();
    }

    [Fact]
    public async Task DisposesInnerSessionOnClose()
    {
        var fakes = new List<FakeRealtimeSession>();
        var session = new ReconnectingRealtimeSession(Cfg(), Factory(fakes), _ => Task.FromResult(Cfg()), Fast());

        await session.OpenAsync(CancellationToken.None);
        await session.CloseAsync(TimeSpan.FromSeconds(1));

        fakes[0].Disposed.Should().BeTrue();
    }

    [Fact]
    public async Task DisposesFailedReconnectAttempts()
    {
        var fakes = new List<FakeRealtimeSession>();
        await using var session = new ReconnectingRealtimeSession(
            Cfg(), ThrowingReconnectFactory(fakes), _ => Task.FromResult(Cfg()), Fast(maxAttempts: 2));
        using var cts = new CancellationTokenSource();
        var collector = new EventCollector(session, cts.Token);

        await session.OpenAsync(CancellationToken.None);
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Connected>().Any());

        fakes[0].Drop();
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.ReconnectionFailed>().Any());

        fakes.Skip(1).Should().HaveCount(2);                      // two failed reconnect attempts
        fakes.Skip(1).Should().OnlyContain(f => f.Disposed);      // each disposed, no leak
        cts.Cancel();
    }

    [Fact]
    public async Task DefersEndTurnDuringReconnectAndFinalizesNewSession()
    {
        var fakes = new List<FakeRealtimeSession>();
        var gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var remintCalls = 0;
        await using var session = new ReconnectingRealtimeSession(
            Cfg(),
            Factory(fakes),
            async _ => { if (Interlocked.Increment(ref remintCalls) == 1) { await gate.Task; } return Cfg(); },
            Fast());
        using var cts = new CancellationTokenSource();
        var collector = new EventCollector(session, cts.Token);

        await session.OpenAsync(CancellationToken.None);
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Connected>().Any());

        fakes[0].Drop();
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Reconnecting>().Any());
        await session.EndTurnAsync(); // deferred — reconnect in flight

        gate.SetResult();
        await collector.WaitFor(e => e.OfType<TranscriptionEvent.Reconnected>().Any());
        await Task.Delay(50);

        fakes[1].EndTurned.Should().BeTrue();  // finalized the reconnected session
        fakes[0].EndTurned.Should().BeFalse(); // never finalized the dead one
        cts.Cancel();
    }

    // ---- helpers ----------------------------------------------------------

    private static Func<RealtimeTranscriptionSessionConfig, IRealtimeTranscriptionSession> Factory(List<FakeRealtimeSession> sink)
        => _ => { var f = new FakeRealtimeSession(); sink.Add(f); return f; };

    // First session opens cleanly (initial connect); every reconnect attempt fails to open.
    private static Func<RealtimeTranscriptionSessionConfig, IRealtimeTranscriptionSession> ThrowingReconnectFactory(List<FakeRealtimeSession> sink)
        => _ => { var f = new FakeRealtimeSession { ThrowOnOpen = sink.Count >= 1 }; sink.Add(f); return f; };

    private sealed class FakeRealtimeSession : IRealtimeTranscriptionSession
    {
        private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>();
        private readonly List<LiveTranscriptSegment> _collected = new();

        public List<byte[]> Sent { get; } = new();
        public bool EndTurned { get; private set; }
        public bool Closed { get; private set; }
        public bool Disposed { get; private set; }
        public bool ThrowOnOpen { get; init; }

        public RealtimeProvider Provider => RealtimeProvider.Deepgram;
        public IAsyncEnumerable<TranscriptionEvent> Events => _events.Reader.ReadAllAsync();
        public IReadOnlyList<LiveTranscriptSegment> CollectedSegments => _collected;

        public Task OpenAsync(CancellationToken ct)
        {
            if (ThrowOnOpen)
            {
                throw new InvalidOperationException("open failed");
            }
            _events.Writer.TryWrite(new TranscriptionEvent.Connected());
            return Task.CompletedTask;
        }

        public Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct)
        {
            Sent.Add(pcm16Mono.ToArray());
            return Task.CompletedTask;
        }

        public Task EndTurnAsync()
        {
            EndTurned = true;
            return Task.CompletedTask;
        }

        public Task CloseAsync(TimeSpan timeout)
        {
            Closed = true;
            _events.Writer.TryComplete();
            return Task.CompletedTask;
        }

        public ValueTask DisposeAsync()
        {
            Disposed = true;
            _events.Writer.TryComplete();
            return ValueTask.CompletedTask;
        }

        public void EmitTranscript(LiveTranscriptSegment segment)
        {
            if (segment.IsFinal)
            {
                _collected.Add(segment);
            }
            _events.Writer.TryWrite(new TranscriptionEvent.Transcript(segment));
        }

        public void EmitWarning(string code, string message)
            => _events.Writer.TryWrite(new TranscriptionEvent.ProviderWarning(code, message));

        public void Drop(string? reason = null)
        {
            _events.Writer.TryWrite(new TranscriptionEvent.Disconnected(reason));
            _events.Writer.TryComplete();
        }
    }

    private sealed class EventCollector
    {
        private readonly List<TranscriptionEvent> _events = new();
        private readonly object _lock = new();

        public EventCollector(IRealtimeTranscriptionSession session, CancellationToken ct)
        {
            _ = Task.Run(async () =>
            {
                try
                {
                    await foreach (var ev in session.Events.WithCancellation(ct))
                    {
                        lock (_lock) { _events.Add(ev); }
                    }
                }
                catch { /* cancelled / completed */ }
            });
        }

        public List<TranscriptionEvent> Snapshot()
        {
            lock (_lock) { return _events.ToList(); }
        }

        public async Task WaitFor(Func<List<TranscriptionEvent>, bool> condition, int timeoutMs = 3000)
        {
            var sw = Stopwatch.StartNew();
            while (sw.ElapsedMilliseconds < timeoutMs)
            {
                if (condition(Snapshot()))
                {
                    return;
                }
                await Task.Delay(10);
            }
            throw new TimeoutException("Condition not met within timeout. Events: "
                + string.Join(", ", Snapshot().Select(e => e.GetType().Name)));
        }
    }
}
