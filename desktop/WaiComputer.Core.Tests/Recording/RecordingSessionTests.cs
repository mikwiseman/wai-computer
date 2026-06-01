using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Audio;
using WaiComputer.Core.Realtime;
using WaiComputer.Core.Recordings;
using WaiComputer.Core.Time;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using WireMock.Server;
using Xunit;
using RecordingModel = WaiComputer.Core.Api.Models.Recording;

namespace WaiComputer.Core.Tests.Recording;

public class RecordingSessionTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;
    private string _dir = null!;
    private RecordingBackupStore _store = null!;
    private FakeClock _clock = null!;
    private FakeMicPermission _mic = null!;
    private FakeNotices _notices = null!;
    private FakeCaptureFactory _factory = null!;
    private FakeSession _session = null!;
    private RecordingSession _rec = null!;

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        _dir = Path.Combine(Path.GetTempPath(), "wc-rec-" + Guid.NewGuid().ToString("N"));
        _store = new RecordingBackupStore(_dir);
        _clock = new FakeClock();
        _mic = new FakeMicPermission { Granted = true };
        _notices = new FakeNotices();
        _factory = new FakeCaptureFactory();
        _session = new FakeSession();
        var sync = new PendingRecordingSyncCoordinator(_client, _store, _clock);
        _rec = new RecordingSession(_client, _factory, _mic, _store, sync, _clock, _notices, _ => _session);
        return Task.CompletedTask;
    }

    public async Task DisposeAsync()
    {
        await _rec.DisposeAsync();
        _client.Dispose();
        _server.Stop();
        _server.Dispose();
        try { Directory.Delete(_dir, recursive: true); } catch { }
    }

    private static string Json<T>(T value) => System.Text.Json.JsonSerializer.Serialize(value, WaiJson.Options);

    private void StubCreateRecording(Guid id) => _server
        .Given(Request.Create().UsingPost().WithPath("/api/recordings"))
        .RespondWith(Response.Create().WithStatusCode(200)
            .WithBody(Json(new RecordingModel(id.ToString(), "Untitled", RecordingType.Meeting, "en", null,
                RecordingStatus.PendingUpload, null, 0, false, _clock.UtcNow, _clock.UtcNow, null, null)))
            .WithHeader("Content-Type", "application/json"));

    private void StubMintSession(int statusCode)
    {
        var resp = Response.Create().WithStatusCode(statusCode);
        if (statusCode == 200)
        {
            resp = resp.WithBody(Json(new RealtimeTranscriptionSessionConfig(
                    RealtimeProvider.Deepgram, "tok", 60, 16000, "linear16", "en", 1, "nova-3",
                    null, null, false, "wss://wai.computer/api/transcription/stream", AuthScheme.Bearer)))
                .WithHeader("Content-Type", "application/json");
        }
        _server.Given(Request.Create().UsingPost().WithPath("/api/transcription/session")).RespondWith(resp);
    }

    private async Task WaitForPhase(RecordingPhase phase, int timeoutMs = 3000)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            if (_rec.State.Phase == phase) return;
            await Task.Delay(10);
        }
        throw new TimeoutException($"Phase {phase} not reached (got {_rec.State.Phase}).");
    }

    [Fact]
    public async Task StartCreatesServerRecordingAndReachesRecording()
    {
        var id = Guid.NewGuid();
        StubCreateRecording(id);
        StubMintSession(200);

        await _rec.StartAsync(RecordingType.Meeting, RecordingInputSource.Dual, "en", null);

        _rec.State.Phase.Should().Be(RecordingPhase.Recording);
        _rec.State.CurrentRecordingId.Should().Be(id.ToString());
        _rec.State.LiveTranscriptionOffline.Should().BeFalse();
        _session.Opened.Should().BeTrue();
        _server.LogEntries.Should().Contain(e => e.RequestMessage.Path == "/api/recordings");
    }

    [Fact]
    public async Task MicrophoneDeniedSetsErrorAndStaysIdle()
    {
        _mic.Granted = false;
        StubCreateRecording(Guid.NewGuid());

        await _rec.StartAsync(RecordingType.Meeting, RecordingInputSource.Dual, "en", null);

        _rec.State.Phase.Should().Be(RecordingPhase.Idle);
        _rec.State.Error.Should().NotBeNull();
        _server.LogEntries.Should().NotContain(e => e.RequestMessage.Path == "/api/recordings");
    }

    [Fact]
    public async Task RealtimeMintFailureDegradesToLocalOnly()
    {
        StubCreateRecording(Guid.NewGuid());
        StubMintSession(500); // session minting fails

        await _rec.StartAsync(RecordingType.Meeting, RecordingInputSource.Dual, "en", null);

        _rec.State.Phase.Should().Be(RecordingPhase.Recording); // recording continues
        _rec.State.LiveTranscriptionOffline.Should().BeTrue();
        _session.Opened.Should().BeFalse(); // never opened — mint threw first
    }

    [Fact]
    public async Task StopFinalizesAndBacksUpTranscriptOnlyWhenNoAudio()
    {
        var id = Guid.NewGuid();
        StubCreateRecording(id);
        StubMintSession(200);

        await _rec.StartAsync(RecordingType.Meeting, RecordingInputSource.Dual, "en", null);
        await _rec.StopAsync();

        _rec.State.Phase.Should().Be(RecordingPhase.Idle);
        var manifest = _store.GetManifest(id);
        manifest.Should().NotBeNull();
        manifest!.HasAudioFile.Should().BeFalse(); // nothing written -> below upload floor -> discarded
    }

    // ----- fakes -----------------------------------------------------------

    private sealed class FakeMicPermission : IMicrophonePermission
    {
        public bool Granted { get; set; } = true;
        public Task<bool> EnsureGrantedAsync(CancellationToken ct) => Task.FromResult(Granted);
    }

    private sealed class FakeNotices : IRecoveryNoticeSink
    {
        public List<string> Posted { get; } = new();
        public void Post(string message) => Posted.Add(message);
    }

    private sealed class FakeClock : ISystemClock
    {
        public DateTimeOffset UtcNow { get; } = new(2026, 6, 1, 12, 0, 0, TimeSpan.Zero);
        // Tiny real delay so the duration/monitor loops + sync backoff progress and terminate quickly.
        public Task Delay(TimeSpan duration, CancellationToken ct) => Task.Delay(5, ct);
    }

    private sealed class FakeCaptureFactory : IAudioCaptureFactory
    {
        public bool RequestSystemAudio { get; init; } = true;
        public DualAudioCapture Create(RecordingInputSource source, out bool requestsSystemAudio)
        {
            requestsSystemAudio = RequestSystemAudio;
            return new DualAudioCapture(new FakeMic(), null, new AudioCaptureConfig());
        }
    }

    private sealed class FakeMic : IMicrophoneCapture
    {
        private readonly Channel<AudioFrame> _frames = Channel.CreateUnbounded<AudioFrame>();
        public AudioSource Source => AudioSource.Microphone;
        public bool IsCapturing { get; private set; }
        public bool HasReceivedAudio => false;
        public DateTimeOffset? LastAudibleAt => null;
        public ChannelReader<AudioFrame> Frames => _frames.Reader;
        public Task StartAsync(CancellationToken ct) { IsCapturing = true; return Task.CompletedTask; }
        public Task StopAsync() { IsCapturing = false; _frames.Writer.TryComplete(); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { _frames.Writer.TryComplete(); return ValueTask.CompletedTask; }
    }

    private sealed class FakeSession : IRealtimeTranscriptionSession
    {
        private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>();
        public bool Opened { get; private set; }
        public bool Closed { get; private set; }
        public RealtimeProvider Provider => RealtimeProvider.Deepgram;
        public IAsyncEnumerable<TranscriptionEvent> Events => _events.Reader.ReadAllAsync();
        public IReadOnlyList<LiveTranscriptSegment> CollectedSegments => Array.Empty<LiveTranscriptSegment>();
        public Task OpenAsync(CancellationToken ct) { Opened = true; _events.Writer.TryWrite(new TranscriptionEvent.Connected()); return Task.CompletedTask; }
        public Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct) => Task.CompletedTask;
        public Task EndTurnAsync() => Task.CompletedTask;
        public Task CloseAsync(TimeSpan timeout) { Closed = true; _events.Writer.TryComplete(); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { _events.Writer.TryComplete(); return ValueTask.CompletedTask; }
    }
}
