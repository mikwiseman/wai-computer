using System.Linq;
using System.Threading.Channels;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Audio;
using WaiComputer.Core.Hotkey;
using WaiComputer.Core.Realtime;
using WaiComputer.Core.Time;

namespace WaiComputer.Core.Dictation;

/// <summary>Lifecycle of a dictation turn (ports the macOS DictationManager phases).</summary>
public enum DictationState
{
    Idle,
    Connecting,
    Listening,
    Processing,
    Inserting,
}

/// <summary>Live, mutable settings the orchestrator reads per turn (platform-backed).</summary>
public interface IDictationSettings
{
    /// <summary>When on, the raw transcript is run through AI cleanup before insertion (no silent fallback to raw on failure).</summary>
    bool PostFilterEnabled { get; }
}

/// <summary>Outcome of a completed dictation turn (for the HUD/history surface).</summary>
public sealed record DictationResult(
    string RawText,
    string InsertedText,
    double DurationSeconds,
    bool WasCleaned,
    bool InsertedViaClipboard);

/// <summary>
/// The dictation keystone: a state machine (idle → connecting → listening →
/// processing → inserting) that drives a realtime transcription turn and inserts
/// the result into the focused app. Ports the macOS <c>DictationManager</c>.
///
/// Wiring: <see cref="Attach"/> binds a <see cref="HotkeyStateMachine"/> so
/// push-to-talk start/stop, double-tap hands-free, and abort map onto the turn.
/// Concurrency: a <see cref="SemaphoreSlim"/> gate serialises Start/Stop/Cancel so
/// only one transition runs at a time; <c>_transitionLock</c> makes the
/// listening-transition and the deferred-stop check atomic (so a push-to-talk
/// release that arrives mid-handshake can't be lost or double-fired); a
/// <c>_collectLock</c> guards the transcript collections the event pump writes and
/// the stop path reads.
/// </summary>
public sealed class DictationOrchestrator : IAsyncDisposable
{
    private const int StartupBufferMaxBytes = 2 * 16000 * 4; // ~4 s of 16 kHz mono int16 pre-roll headroom
    private static readonly TimeSpan FinalEventDrainWindow = TimeSpan.FromMilliseconds(400);
    private static readonly TimeSpan CloseTimeout = TimeSpan.FromMilliseconds(2500);
    private static readonly TimeSpan CancelCloseTimeout = TimeSpan.FromMilliseconds(400);
    private static readonly TimeSpan PumpJoinTimeout = TimeSpan.FromSeconds(5);

    private readonly IApiClient _api;
    private readonly IRealtimeSessionFactory _sessionFactory;
    private readonly IMicrophonePreRollCapture _mic;
    private readonly ITextInserter _textInserter;
    private readonly DictationHistoryStore _history;
    private readonly DictationDictionaryStore _dictionary;
    private readonly DictationLanguageStore _languageStore;
    private readonly IDictationSettings _settings;
    private readonly ISystemClock _clock;
    private readonly ILogger<DictationOrchestrator> _logger;

    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly object _transitionLock = new();
    private readonly object _collectLock = new();
    private readonly CancellationTokenSource _lifetimeCts = new();

    // Guarded by _transitionLock.
    private DictationState _state = DictationState.Idle;
    private bool _handsFree;
    private bool _deferredStop;
    private DateTimeOffset _sessionStartedAt;

    // Guarded by _collectLock.
    private readonly List<string> _finals = new();
    private string _lastInterim = string.Empty;

    // Mutated only under _gate (the Start/Stop/Cancel critical section).
    private IRealtimeTranscriptionSession? _session;
    private CancellationTokenSource? _sessionCts;
    private Task? _audioPumpTask;
    private Task? _eventPumpTask;
    private bool _prewarmed;
    private bool _disposed;

    public DictationOrchestrator(
        IApiClient api,
        IRealtimeSessionFactory sessionFactory,
        IMicrophonePreRollCapture mic,
        ITextInserter textInserter,
        DictationHistoryStore history,
        DictationDictionaryStore dictionary,
        DictationLanguageStore languageStore,
        IDictationSettings settings,
        ISystemClock clock,
        ILogger<DictationOrchestrator>? logger = null)
    {
        _api = api;
        _sessionFactory = sessionFactory;
        _mic = mic;
        _textInserter = textInserter;
        _history = history;
        _dictionary = dictionary;
        _languageStore = languageStore;
        _settings = settings;
        _clock = clock;
        _logger = logger ?? NullLogger<DictationOrchestrator>.Instance;
    }

    /// <summary>Current lifecycle state.</summary>
    public DictationState State { get { lock (_transitionLock) { return _state; } } }

    public event Action<DictationState>? StateChanged;
    public event Action<string>? InterimTranscriptUpdated;
    public event Action<DictationResult>? Completed;
    /// <summary>Raised when automatic insertion failed; the payload text is already on the clipboard for manual paste.</summary>
    public event Action<string>? ClipboardRecoveryRequired;
    public event Action<string>? Failed;

    /// <summary>Bind a hotkey state machine so push-to-talk / hands-free / abort drive the turn.</summary>
    public void Attach(HotkeyStateMachine hotkey)
    {
        hotkey.PushToTalkStart += OnPushToTalkStart;
        hotkey.PushToTalkStop += OnPushToTalkStop;
        hotkey.HandsFreeToggle += OnHandsFreeToggle;
        hotkey.Cancelled += OnCancelled;
    }

    /// <summary>Warm the microphone + pre-roll ahead of a turn (e.g. on hotkey key-down) so the first words aren't clipped. Idempotent.</summary>
    public async Task PrewarmAsync(CancellationToken ct)
    {
        if (_prewarmed)
        {
            return;
        }
        await _mic.PrewarmAsync(ct).ConfigureAwait(false);
        _prewarmed = true;
    }

    public Task StartAsync(CancellationToken ct = default) => StartAsync(handsFree: false, ct);

    public async Task StartAsync(bool handsFree, CancellationToken ct = default)
    {
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        var started = false;
        var fireDeferredStop = false;
        try
        {
            lock (_transitionLock)
            {
                if (_state != DictationState.Idle)
                {
                    return; // a turn is already in flight — ignore re-entrant start
                }
                _handsFree = handsFree;
                _deferredStop = false;
            }

            SetState(DictationState.Connecting);
            lock (_collectLock) { _finals.Clear(); _lastInterim = string.Empty; }

            await PrewarmAsync(ct).ConfigureAwait(false);
            var lease = _mic.Lease();
            var startupBuffer = new DictationStartupAudioBuffer(StartupBufferMaxBytes);

            // Buffer the pre-roll first so it streams ahead of any live frame.
            foreach (var frame in lease.PreRoll)
            {
                await startupBuffer.AppendAsync(frame.Pcm16, ct).ConfigureAwait(false);
            }

            var language = DictationLanguageSelectionPolicy.ProviderLanguage(_languageStore.WireLanguageTag);
            var config = await _api.CreateRealtimeTranscriptionSessionAsync(
                new CreateRealtimeTranscriptionSessionRequest(language, 1, "dictation"), ct).ConfigureAwait(false);

            var session = _sessionFactory.Create(config);
            var sessionCts = CancellationTokenSource.CreateLinkedTokenSource(_lifetimeCts.Token);

            // Start the event pump before opening so no early transcript/lifecycle event is missed.
            var eventPump = Task.Run(() => EventPumpAsync(session, sessionCts.Token));

            await session.OpenAsync(ct).ConfigureAwait(false);

            // Start the audio pump (buffers live frames) before flipping the buffer to pass-through,
            // so frames captured during the flush are queued in capture order rather than dropped.
            var audioPump = Task.Run(() => AudioPumpAsync(lease, startupBuffer, sessionCts.Token));
            await startupBuffer.StartStreamingAsync(session.SendPcmAsync, sessionCts.Token).ConfigureAwait(false);

            _session = session;
            _sessionCts = sessionCts;
            _audioPumpTask = audioPump;
            _eventPumpTask = eventPump;
            started = true;

            lock (_transitionLock)
            {
                _state = DictationState.Listening;
                _sessionStartedAt = _clock.UtcNow;
                fireDeferredStop = _deferredStop;
                _deferredStop = false;
            }
            StateChanged?.Invoke(DictationState.Listening);
        }
        catch (Exception ex)
        {
            if (!started)
            {
                await RollbackStartAsync().ConfigureAwait(false);
            }
            SetState(DictationState.Idle);
            if (ex is OperationCanceledException)
            {
                throw;
            }
            _logger.LogError(ex, "Dictation start failed");
            Failed?.Invoke(ex.Message);
            return;
        }
        finally
        {
            _gate.Release();
        }

        if (fireDeferredStop)
        {
            await StopAndInsertAsync(ct).ConfigureAwait(false);
        }
    }

    public async Task StopAndInsertAsync(CancellationToken ct = default)
    {
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            lock (_transitionLock)
            {
                if (_state != DictationState.Listening)
                {
                    return; // nothing live to finalize
                }
                _state = DictationState.Processing;
            }
            StateChanged?.Invoke(DictationState.Processing);

            var session = _session!;
            var startedAt = _sessionStartedAt;

            // Keep capturing the tail of the last word, then close the mic so the audio pump drains.
            await _clock.Delay(DictationFinalizationPolicy.CaptureTailDelay, ct).ConfigureAwait(false);
            await _mic.TeardownAsync().ConfigureAwait(false);
            _prewarmed = false;
            await JoinPumpAsync(_audioPumpTask).ConfigureAwait(false);

            await session.EndTurnAsync().ConfigureAwait(false);
            await _clock.Delay(FinalEventDrainWindow, ct).ConfigureAwait(false);
            await session.CloseAsync(CloseTimeout).ConfigureAwait(false);
            await JoinPumpAsync(_eventPumpTask).ConfigureAwait(false);

            var raw = SelectTranscript(session);
            if (raw.Length == 0)
            {
                await CleanupSessionAsync().ConfigureAwait(false);
                SetState(DictationState.Idle);
                return;
            }

            var replaced = _dictionary.ApplyReplacements(raw);

            string toInsert;
            if (_settings.PostFilterEnabled)
            {
                string? cleaned = null;
                var cleanupFailed = false;
                try
                {
                    cleaned = await _api.CleanupDictationAsync(replaced, _dictionary.VocabularyList, ct).ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    cleanupFailed = true;
                    _logger.LogWarning(ex, "Dictation cleanup request failed");
                }

                try
                {
                    toInsert = DictationCleanupPolicy.TextToInsert(postFilterEnabled: true, replaced, cleaned, cleanupFailed);
                }
                catch (DictationCleanupException ex)
                {
                    await CleanupSessionAsync().ConfigureAwait(false);
                    SetState(DictationState.Idle);
                    Failed?.Invoke(ex.Message);
                    return;
                }
            }
            else
            {
                toInsert = DictationCleanupPolicy.TextToInsert(postFilterEnabled: false, replaced, null, false);
            }

            SetState(DictationState.Inserting);

            var insertedViaClipboard = false;
            try
            {
                await _textInserter.InsertAsync(toInsert, ct).ConfigureAwait(false);
            }
            catch (TextInsertionException ex)
            {
                insertedViaClipboard = true;
                _logger.LogWarning(ex, "Automatic text insertion failed; routed to clipboard recovery");
                ClipboardRecoveryRequired?.Invoke(toInsert);
            }

            var duration = Math.Max(0, (_clock.UtcNow - startedAt).TotalSeconds);
            var wasCleaned = !string.Equals(toInsert, raw, StringComparison.Ordinal);
            await _history.AddAsync(raw, wasCleaned ? toInsert : null, duration, ct).ConfigureAwait(false);

            await CleanupSessionAsync().ConfigureAwait(false);
            SetState(DictationState.Idle);
            Completed?.Invoke(new DictationResult(raw, toInsert, duration, wasCleaned, insertedViaClipboard));
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task CancelAsync(CancellationToken ct = default)
    {
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            lock (_transitionLock)
            {
                _deferredStop = false;
                if (_state == DictationState.Idle)
                {
                    return;
                }
            }

            _sessionCts?.Cancel();
            await TeardownMicQuietlyAsync().ConfigureAwait(false);
            if (_session is { } session)
            {
                try { await session.CloseAsync(CancelCloseTimeout).ConfigureAwait(false); }
                catch (Exception ex) { _logger.LogWarning(ex, "Dictation cancel close failed"); }
            }
            await CleanupSessionAsync().ConfigureAwait(false);
            SetState(DictationState.Idle);
        }
        finally
        {
            _gate.Release();
        }
    }

    private async Task ToggleHandsFreeAsync()
    {
        DictationState state;
        lock (_transitionLock) { state = _state; }
        if (state == DictationState.Idle)
        {
            await StartAsync(handsFree: true, _lifetimeCts.Token).ConfigureAwait(false);
        }
        else if (state == DictationState.Listening)
        {
            await StopAndInsertAsync(_lifetimeCts.Token).ConfigureAwait(false);
        }
        // Connecting/Processing/Inserting: ignore — the in-flight transition owns the turn.
    }

    // ---- hotkey handlers (fire-and-forget; never throw into the hotkey thread) ----

    private void OnPushToTalkStart() => FireAndForget(() => StartAsync(handsFree: false, _lifetimeCts.Token));

    private void OnPushToTalkStop()
    {
        bool finishNow = false;
        lock (_transitionLock)
        {
            var resolution = PushToTalkStopPolicy.Resolve(MapStopState(_state), _handsFree);
            if (resolution == PushToTalkStopResolution.FinishNow)
            {
                finishNow = true;
            }
            else if (resolution == PushToTalkStopResolution.DeferUntilReady)
            {
                _deferredStop = true;
            }
        }
        if (finishNow)
        {
            FireAndForget(() => StopAndInsertAsync(_lifetimeCts.Token));
        }
    }

    private void OnHandsFreeToggle() => FireAndForget(ToggleHandsFreeAsync);

    private void OnCancelled() => FireAndForget(() => CancelAsync(_lifetimeCts.Token));

    // ---- pumps ----

    private async Task AudioPumpAsync(DictationAudioLease lease, DictationStartupAudioBuffer buffer, CancellationToken sendToken)
    {
        try
        {
            // Read with None so a normal stop (mic channel completes) drains cleanly; the SEND honours
            // the session token so a hard cancel can't hang waiting on a dead provider socket.
            await foreach (var frame in lease.Frames.ReadAllAsync(CancellationToken.None).ConfigureAwait(false))
            {
                if (frame.IsEmpty)
                {
                    continue;
                }
                await buffer.AppendAsync(frame.Pcm16, sendToken).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) { /* hard cancel */ }
        catch (DictationStartupAudioBufferException ex) { _logger.LogError(ex, "Dictation startup buffer overflow"); }
        catch (Exception ex) { _logger.LogWarning(ex, "Dictation audio pump ended on error"); }
    }

    private async Task EventPumpAsync(IRealtimeTranscriptionSession session, CancellationToken ct)
    {
        try
        {
            await foreach (var ev in session.Events.WithCancellation(ct).ConfigureAwait(false))
            {
                switch (ev)
                {
                    case TranscriptionEvent.Transcript t:
                        if (t.Segment.IsFinal)
                        {
                            lock (_collectLock) { _finals.Add(t.Segment.Text); _lastInterim = string.Empty; }
                        }
                        else
                        {
                            lock (_collectLock) { _lastInterim = t.Segment.Text; }
                            InterimTranscriptUpdated?.Invoke(t.Segment.Text);
                        }
                        break;

                    case TranscriptionEvent.ProviderWarning w when TranscriptionErrorCodes.Fatal.Contains(w.Code):
                        _logger.LogError("Fatal realtime provider error during dictation: {Code}", w.Code);
                        Failed?.Invoke(w.Message);
                        FireAndForget(() => CancelAsync(_lifetimeCts.Token));
                        return;
                }
            }
        }
        catch (OperationCanceledException) { /* session torn down */ }
        catch (Exception ex) { _logger.LogWarning(ex, "Dictation event pump ended on error"); }
    }

    // ---- helpers ----

    private string SelectTranscript(IRealtimeTranscriptionSession session)
    {
        List<string> finals;
        string lastInterim;
        lock (_collectLock) { finals = _finals.ToList(); lastInterim = _lastInterim; }

        var collected = string.Join(" ", session.CollectedSegments.Where(s => s.IsFinal).Select(s => s.Text));
        var pumped = string.Join(" ", finals);
        return RealtimeTranscriptCandidateSelector.Select(new[] { collected, pumped, lastInterim });
    }

    private void SetState(DictationState next)
    {
        bool changed;
        lock (_transitionLock)
        {
            changed = _state != next;
            _state = next;
        }
        if (changed)
        {
            StateChanged?.Invoke(next);
        }
    }

    private async Task RollbackStartAsync()
    {
        _sessionCts?.Cancel();
        await TeardownMicQuietlyAsync().ConfigureAwait(false);
        if (_session is { } session)
        {
            try { await session.CloseAsync(CancelCloseTimeout).ConfigureAwait(false); }
            catch (Exception ex) { _logger.LogWarning(ex, "Dictation start-rollback close failed"); }
        }
        await CleanupSessionAsync().ConfigureAwait(false);
    }

    private async Task CleanupSessionAsync()
    {
        await JoinPumpAsync(_audioPumpTask).ConfigureAwait(false);
        await JoinPumpAsync(_eventPumpTask).ConfigureAwait(false);
        if (_session is { } session)
        {
            try { await session.DisposeAsync().ConfigureAwait(false); }
            catch (Exception ex) { _logger.LogWarning(ex, "Dictation session dispose failed"); }
        }
        _sessionCts?.Dispose();
        _session = null;
        _sessionCts = null;
        _audioPumpTask = null;
        _eventPumpTask = null;
    }

    private async Task TeardownMicQuietlyAsync()
    {
        try { await _mic.TeardownAsync().ConfigureAwait(false); }
        catch (Exception ex) { _logger.LogWarning(ex, "Dictation mic teardown failed"); }
        _prewarmed = false;
    }

    private async Task JoinPumpAsync(Task? pump)
    {
        if (pump is null)
        {
            return;
        }
        var completed = await Task.WhenAny(pump, _clock.Delay(PumpJoinTimeout, CancellationToken.None)).ConfigureAwait(false);
        if (completed != pump)
        {
            _logger.LogWarning("Dictation pump did not complete within the join timeout");
        }
    }

    private void FireAndForget(Func<Task> op) => _ = Task.Run(async () =>
    {
        try { await op().ConfigureAwait(false); }
        catch (OperationCanceledException) { /* expected on cancel/shutdown */ }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Dictation hotkey operation failed");
            Failed?.Invoke(ex.Message);
        }
    });

    private static PushToTalkStopState MapStopState(DictationState state) => state switch
    {
        DictationState.Idle => PushToTalkStopState.Idle,
        DictationState.Connecting => PushToTalkStopState.Connecting,
        DictationState.Listening => PushToTalkStopState.Listening,
        _ => PushToTalkStopState.Finalizing,
    };

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        _lifetimeCts.Cancel();
        try { await CancelAsync(CancellationToken.None).ConfigureAwait(false); }
        catch (Exception ex) { _logger.LogWarning(ex, "Dictation dispose cancel failed"); }
        _lifetimeCts.Dispose();
        _gate.Dispose();
    }
}
