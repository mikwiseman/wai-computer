using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Audio;
using WaiComputer.Core.Dictation;
using WaiComputer.Core.Hotkey;
using WaiComputer.Core.Realtime;
using WaiComputer.Core.Time;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using WireMock.Server;
using Xunit;

namespace WaiComputer.Core.Tests.Dictation;

public class DictationOrchestratorTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;
    private FakeMicPreRoll _mic = null!;
    private FakeSessionFactory _factory = null!;
    private FakeTextInserter _inserter = null!;
    private FakeSettings _settings = null!;
    private FakeLocalStore _local = null!;
    private DictationHistoryStore _history = null!;
    private DictationDictionaryStore _dictionary = null!;
    private DictationLanguageStore _language = null!;
    private DictationOrchestrator _orch = null!;

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        _mic = new FakeMicPreRoll();
        _factory = new FakeSessionFactory();
        _inserter = new FakeTextInserter();
        _settings = new FakeSettings();
        _local = new FakeLocalStore();
        var clock = new FakeClock();
        _history = new DictationHistoryStore(_local, _client, clock);
        _dictionary = new DictationDictionaryStore(_local, _client, clock);
        _language = new DictationLanguageStore(new FakePrefs());
        _orch = new DictationOrchestrator(_client, _factory, _mic, _inserter, _history, _dictionary, _language, _settings, clock);
        return Task.CompletedTask;
    }

    public async Task DisposeAsync()
    {
        await _orch.DisposeAsync();
        _client.Dispose();
        _server.Stop();
        _server.Dispose();
    }

    private static string Json<T>(T value) => System.Text.Json.JsonSerializer.Serialize(value, WaiJson.Options);

    private void StubMint(int delayMs = 0)
    {
        var resp = Response.Create().WithStatusCode(200)
            .WithBody(Json(new RealtimeTranscriptionSessionConfig(
                RealtimeProvider.Deepgram, "tok", 60, 16000, "linear16", "multi", 1, "nova-3",
                null, null, false, "wss://wai.computer/api/transcription/stream", AuthScheme.Bearer)))
            .WithHeader("Content-Type", "application/json");
        if (delayMs > 0)
        {
            resp = resp.WithDelay(TimeSpan.FromMilliseconds(delayMs));
        }
        _server.Given(Request.Create().UsingPost().WithPath("/api/transcription/session")).RespondWith(resp);
    }

    private void StubCleanup(int statusCode, string? text = null)
    {
        var resp = Response.Create().WithStatusCode(statusCode);
        if (statusCode == 200)
        {
            resp = resp.WithBody(Json(new { text })).WithHeader("Content-Type", "application/json");
        }
        _server.Given(Request.Create().UsingPost().WithPath("/api/dictation/cleanup")).RespondWith(resp);
    }

    private async Task WaitFor(Func<bool> condition, int timeoutMs = 5000)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            if (condition()) return;
            await Task.Delay(10);
        }
        throw new TimeoutException("Condition not met within timeout.");
    }

    [Fact]
    public async Task PushToTalkTurnTranscribesAndInserts()
    {
        StubMint();
        _factory.AutoFinal = "hello world";

        DictationResult? completed = null;
        _orch.Completed += r => completed = r;

        await _orch.StartAsync(handsFree: false);
        _orch.State.Should().Be(DictationState.Listening);
        await _orch.StopAndInsertAsync();

        _orch.State.Should().Be(DictationState.Idle);
        _inserter.Inserted.Should().ContainSingle().Which.Should().Be("hello world");
        completed.Should().NotBeNull();
        completed!.RawText.Should().Be("hello world");
        completed.InsertedViaClipboard.Should().BeFalse();
        _factory.Last!.EndTurned.Should().BeTrue();
        _factory.Last.Closed.Should().BeTrue();
    }

    [Fact]
    public async Task AppliesDictionaryReplacementsBeforeInsert()
    {
        StubMint();
        _local.Seed("dictation_dictionary", new List<DictionaryWord>
        {
            new(Guid.NewGuid(), "teh", "the", new DateTimeOffset(2026, 6, 1, 12, 0, 0, TimeSpan.Zero)),
        });
        await _dictionary.LoadAsync(CancellationToken.None);
        _factory.AutoFinal = "teh quick fox";

        await _orch.StartAsync();
        await _orch.StopAndInsertAsync();

        _inserter.Inserted.Should().ContainSingle().Which.Should().Be("the quick fox");
    }

    [Fact]
    public async Task PostFilterCleanupReplacesInsertedText()
    {
        StubMint();
        StubCleanup(200, "Cleaned text.");
        _settings.PostFilterEnabled = true;
        _factory.AutoFinal = "cleaned text";

        DictationResult? completed = null;
        _orch.Completed += r => completed = r;

        await _orch.StartAsync();
        await _orch.StopAndInsertAsync();

        _inserter.Inserted.Should().ContainSingle().Which.Should().Be("Cleaned text.");
        completed!.WasCleaned.Should().BeTrue();
    }

    [Fact]
    public async Task PostFilterFailureSurfacesAndDoesNotInsertRaw()
    {
        StubMint();
        StubCleanup(500); // cleanup endpoint fails
        _settings.PostFilterEnabled = true;
        _factory.AutoFinal = "raw transcript";

        string? failure = null;
        _orch.Failed += m => failure = m;

        await _orch.StartAsync();
        await _orch.StopAndInsertAsync();

        _orch.State.Should().Be(DictationState.Idle);
        _inserter.Inserted.Should().BeEmpty(); // no silent fallback to raw
        failure.Should().NotBeNull();
    }

    [Fact]
    public async Task EmptyTranscriptInsertsNothing()
    {
        StubMint();
        _factory.AutoFinal = null; // provider returns nothing

        DictationResult? completed = null;
        _orch.Completed += r => completed = r;

        await _orch.StartAsync();
        await _orch.StopAndInsertAsync();

        _orch.State.Should().Be(DictationState.Idle);
        _inserter.Inserted.Should().BeEmpty();
        completed.Should().BeNull();
    }

    [Fact]
    public async Task InsertFailureRoutesToClipboardRecovery()
    {
        StubMint();
        _factory.AutoFinal = "needs clipboard";
        _inserter.ThrowOnInsert = true;

        string? recovery = null;
        DictationResult? completed = null;
        _orch.ClipboardRecoveryRequired += t => recovery = t;
        _orch.Completed += r => completed = r;

        await _orch.StartAsync();
        await _orch.StopAndInsertAsync();

        recovery.Should().Be("needs clipboard");
        completed!.InsertedViaClipboard.Should().BeTrue();
        _orch.State.Should().Be(DictationState.Idle);
    }

    [Fact]
    public async Task FatalProviderErrorCancelsTurnWithoutInserting()
    {
        StubMint();
        await _orch.StartAsync();
        _orch.State.Should().Be(DictationState.Listening);

        string? failure = null;
        _orch.Failed += m => failure = m;
        _factory.Last!.EmitWarning(TranscriptionErrorCodes.AuthError, "auth failed");

        await WaitFor(() => _orch.State == DictationState.Idle);
        failure.Should().NotBeNull();
        _inserter.Inserted.Should().BeEmpty();
    }

    [Fact]
    public async Task DoubleStartIsIgnoredWhileListening()
    {
        StubMint();
        _factory.AutoFinal = "once";

        await _orch.StartAsync();
        await _orch.StartAsync(); // re-entrant start must be a no-op

        _orch.State.Should().Be(DictationState.Listening);
        _factory.CreatedCount.Should().Be(1);
    }

    [Fact]
    public async Task PushToTalkReleaseDuringConnectingDefersThenFinalizes()
    {
        // Mint is delayed so the release lands while the orchestrator is still Connecting:
        // the stop must be deferred and then fire automatically once Listening is reached.
        StubMint(delayMs: 300);
        _factory.AutoFinal = "deferred hello";

        var hotkey = new HotkeyStateMachine();
        _orch.Attach(hotkey);

        var t0 = new DateTimeOffset(2026, 6, 1, 12, 0, 0, TimeSpan.Zero);
        hotkey.OnKeyDown(t0);
        hotkey.Tick(t0 + TimeSpan.FromMilliseconds(200)); // crosses hold threshold -> PushToTalkStart

        await WaitFor(() => _orch.State == DictationState.Connecting, timeoutMs: 2000);
        hotkey.OnKeyUp(t0 + TimeSpan.FromMilliseconds(250)); // release while connecting -> deferred stop

        await WaitFor(() => _orch.State == DictationState.Idle);
        _inserter.Inserted.Should().ContainSingle().Which.Should().Be("deferred hello");
    }

    [Fact]
    public async Task TrailingInterimIsFusedWithFinalsNotDropped()
    {
        // finals = ["hello world", "how are"] + un-finalized tail interim "you".
        // The superset-only selector must receive ONE fused live candidate, else "you" is lost.
        StubMint();
        _factory.AutoFinal = null;

        await _orch.StartAsync();
        var session = _factory.Last!;
        session.EmitFinal("hello world");
        session.EmitFinal("how are");
        session.EmitInterim("you"); // never finalized — only carried by _lastInterim

        await _orch.StopAndInsertAsync();

        _inserter.Inserted.Should().ContainSingle().Which.Should().Be("hello world how are you");
    }

    [Fact]
    public async Task FatalProviderErrorDuringFinalizeDoesNotInsertOrComplete()
    {
        // A fatal warning lands in the finalize drain window (emitted on EndTurn): the turn must
        // abort — no insertion, no Completed — even though a partial transcript exists.
        StubMint();
        _factory.AutoFinal = "partial speech so far";
        _factory.WarnOnEndTurn = (TranscriptionErrorCodes.SessionTimeLimitExceeded, "session time limit exceeded");

        string? failure = null;
        DictationResult? completed = null;
        _orch.Failed += m => failure = m;
        _orch.Completed += r => completed = r;

        await _orch.StartAsync();
        await _orch.StopAndInsertAsync();

        failure.Should().NotBeNull();
        completed.Should().BeNull();
        _inserter.Inserted.Should().BeEmpty();
        await WaitFor(() => _orch.State == DictationState.Idle);
    }

    // ----- fakes -----------------------------------------------------------

    private sealed class FakeMicPreRoll : IMicrophonePreRollCapture
    {
        private readonly Channel<AudioFrame> _frames = Channel.CreateUnbounded<AudioFrame>();
        public List<AudioFrame> PreRoll { get; } = new();
        public bool Prewarmed { get; private set; }
        public bool ToreDown { get; private set; }

        public Task PrewarmAsync(CancellationToken ct) { Prewarmed = true; return Task.CompletedTask; }
        public DictationAudioLease Lease() => new(PreRoll, _frames.Reader);
        public Task TeardownAsync() { ToreDown = true; _frames.Writer.TryComplete(); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { _frames.Writer.TryComplete(); return ValueTask.CompletedTask; }
    }

    private sealed class FakeSessionFactory : IRealtimeSessionFactory
    {
        public string? AutoFinal { get; set; }
        public (string Code, string Message)? WarnOnEndTurn { get; set; }
        public int CreatedCount { get; private set; }
        public FakeSession? Last { get; private set; }

        public IRealtimeTranscriptionSession Create(RealtimeTranscriptionSessionConfig config)
        {
            CreatedCount++;
            Last = new FakeSession(AutoFinal, WarnOnEndTurn);
            return Last;
        }
    }

    private sealed class FakeSession : IRealtimeTranscriptionSession
    {
        private readonly Channel<TranscriptionEvent> _events = Channel.CreateUnbounded<TranscriptionEvent>();
        private readonly List<LiveTranscriptSegment> _collected = new();
        private readonly object _lock = new();
        private readonly string? _autoFinal;
        private readonly (string Code, string Message)? _warnOnEndTurn;

        public FakeSession(string? autoFinal, (string Code, string Message)? warnOnEndTurn = null)
        {
            _autoFinal = autoFinal;
            _warnOnEndTurn = warnOnEndTurn;
        }

        public bool Opened { get; private set; }
        public bool Closed { get; private set; }
        public bool EndTurned { get; private set; }
        public RealtimeProvider Provider => RealtimeProvider.Deepgram;
        public IAsyncEnumerable<TranscriptionEvent> Events => _events.Reader.ReadAllAsync();
        public IReadOnlyList<LiveTranscriptSegment> CollectedSegments { get { lock (_lock) { return _collected.ToList(); } } }

        public Task OpenAsync(CancellationToken ct)
        {
            Opened = true;
            _events.Writer.TryWrite(new TranscriptionEvent.Connected());
            if (_autoFinal is not null)
            {
                EmitFinal(_autoFinal);
            }
            return Task.CompletedTask;
        }

        public void EmitFinal(string text)
        {
            var seg = new LiveTranscriptSegment(text, null, true, 0, 0, 1);
            lock (_lock) { _collected.Add(seg); }
            _events.Writer.TryWrite(new TranscriptionEvent.Transcript(seg));
        }

        public void EmitInterim(string text)
            => _events.Writer.TryWrite(new TranscriptionEvent.Transcript(new LiveTranscriptSegment(text, null, false, 0, 0, 1)));

        public void EmitWarning(string code, string message)
            => _events.Writer.TryWrite(new TranscriptionEvent.ProviderWarning(code, message));

        public Task SendPcmAsync(ReadOnlyMemory<byte> pcm16Mono, CancellationToken ct) => Task.CompletedTask;

        public Task EndTurnAsync()
        {
            EndTurned = true;
            // Inject a provider warning into the finalize drain window (deterministic).
            if (_warnOnEndTurn is { } w)
            {
                EmitWarning(w.Code, w.Message);
            }
            return Task.CompletedTask;
        }

        public Task CloseAsync(TimeSpan timeout) { Closed = true; _events.Writer.TryComplete(); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { _events.Writer.TryComplete(); return ValueTask.CompletedTask; }
    }

    private sealed class FakeTextInserter : ITextInserter
    {
        public List<string> Inserted { get; } = new();
        public bool ThrowOnInsert { get; set; }
        public bool SupportsAutomaticPaste => true;
        public bool HasInsertPermission => true;

        public Task InsertAsync(string text, CancellationToken ct)
        {
            if (ThrowOnInsert)
            {
                throw new TextInsertionException("paste failed");
            }
            Inserted.Add(text);
            return Task.CompletedTask;
        }
    }

    private sealed class FakeSettings : IDictationSettings
    {
        public bool PostFilterEnabled { get; set; }
    }

    private sealed class FakeClock : ISystemClock
    {
        public DateTimeOffset UtcNow => new(2026, 6, 1, 12, 0, 0, TimeSpan.Zero);
        public Task Delay(TimeSpan duration, CancellationToken ct) => Task.Delay(5, ct);
    }

    private sealed class FakePrefs : IPreferences
    {
        private readonly Dictionary<string, string> _values = new();
        public string? Get(string key) => _values.TryGetValue(key, out var v) ? v : null;
        public void Set(string key, string value) => _values[key] = value;
    }

    private sealed class FakeLocalStore : IDictationLocalStore
    {
        private readonly Dictionary<string, object?> _values = new();
        public void Seed<T>(string key, T value) => _values[key] = value;
        public Task<T?> ReadAsync<T>(string key, CancellationToken ct)
            => Task.FromResult(_values.TryGetValue(key, out var v) && v is T t ? t : default);
        public Task WriteAsync<T>(string key, T value, CancellationToken ct)
        {
            _values[key] = value;
            return Task.CompletedTask;
        }
    }
}
