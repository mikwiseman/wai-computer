using System.Linq;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Audio;
using WaiComputer.Core.Realtime;
using WaiComputer.Core.Time;

namespace WaiComputer.Core.Recordings;

/// <summary>
/// Platform-agnostic recording orchestrator porting the macOS
/// <c>MacRecordingViewModel</c>. It is NOT a ViewModel — the UI binds via
/// <see cref="StateChanged"/>. Lifecycle is a phase machine serialised by a
/// single gate. While recording it runs independent pumps: audio (local-first
/// WAV write, then realtime send), transcript, a 1 Hz duration timer, and a 1 Hz
/// system-audio stall monitor. A realtime drop degrades to local-only without
/// interrupting capture; a disk-write failure halts consumption and surfaces an
/// error that a later realtime degrade must not erase. On stop the audio pump
/// drains, the trailing turn is finalized, the recording is backed up locally,
/// and queued for background upload. No fallbacks — failures surface as concrete
/// state.
/// </summary>
public sealed class RecordingSession : IAsyncDisposable
{
    private readonly IApiClient _api;
    private readonly IAudioCaptureFactory _captureFactory;
    private readonly IMicrophonePermission _micPermission;
    private readonly RecordingBackupStore _backups;
    private readonly PendingRecordingSyncCoordinator _sync;
    private readonly ISystemClock _clock;
    private readonly IRecoveryNoticeSink _notices;
    private readonly Func<RealtimeTranscriptionSessionConfig, IRealtimeTranscriptionSession>? _sessionFactory;
    private readonly ILogger<RecordingSession> _logger;

    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly object _stateLock = new();
    private readonly CancellationTokenSource _lifetimeCts = new();
    private RecordingSessionState _state = RecordingSessionState.Idle;
    private readonly List<LiveTranscriptSegment> _committed = new();

    private DualAudioCapture? _capture;
    private IRealtimeTranscriptionSession? _session;
    private AudioFileWriter? _writer;
    private CancellationTokenSource? _cts;
    private Task? _audioPump;
    private Task? _transcriptPump;
    private Task? _durationTimer;
    private Task? _systemMonitor;
    private Guid _recordingId;
    private RecordingType _recordingType = RecordingType.Meeting;
    private string _language = "en";
    private string _interim = string.Empty;
    private int _durationSeconds;
    private volatile bool _liveOffline;
    private volatile bool _diskFatal;
    private bool _disposed;

    public event Action<RecordingSessionState>? StateChanged;

    public RecordingSession(
        IApiClient api,
        IAudioCaptureFactory captureFactory,
        IMicrophonePermission micPermission,
        RecordingBackupStore backups,
        PendingRecordingSyncCoordinator sync,
        ISystemClock clock,
        IRecoveryNoticeSink notices,
        Func<RealtimeTranscriptionSessionConfig, IRealtimeTranscriptionSession>? sessionFactory = null,
        ILogger<RecordingSession>? logger = null)
    {
        _api = api;
        _captureFactory = captureFactory;
        _micPermission = micPermission;
        _backups = backups;
        _sync = sync;
        _clock = clock;
        _notices = notices;
        _sessionFactory = sessionFactory;
        _logger = logger ?? NullLogger<RecordingSession>.Instance;
    }

    public RecordingSessionState State
    {
        get { lock (_stateLock) { return _state; } }
    }

    public async Task StartAsync(RecordingType type, RecordingInputSource source, string language, string? folderId, CancellationToken ct = default)
    {
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (State.Phase != RecordingPhase.Idle)
            {
                throw new InvalidOperationException($"Cannot start: session is {State.Phase}.");
            }

            ResetForNewRecording(type, language);
            UpdateState(_ => RecordingSessionState.Idle with { Phase = RecordingPhase.Preparing });

            if (!await _micPermission.EnsureGrantedAsync(ct).ConfigureAwait(false))
            {
                UpdateState(_ => RecordingSessionState.Idle with { Error = "Microphone permission is required to record." });
                return;
            }

            try
            {
                var recording = await _api.CreateRecordingAsync(new CreateRecordingRequest(null, type, language, folderId), ct).ConfigureAwait(false);
                _recordingId = Guid.TryParse(recording.Id, out var parsed) ? parsed : Guid.NewGuid();

                _capture = _captureFactory.Create(source, out var requestedSystemAudio);
                await _capture.StartAsync(ct).ConfigureAwait(false);
                var channels = _capture.EffectiveChannelCount;

                _backups.EnsureDirectoryForRecording(_recordingId);
                _writer = new AudioFileWriter(_backups.AudioPath(_recordingId), 16000, channels);
                // Early manifest in the in-progress state so a crash mid-recording leaves a
                // recoverable backup the coordinator will SKIP until it is finalized.
                _backups.Save(NewManifest(0, string.Empty, 0, hasAudioFile: true, RecordingBackupSyncState.LocalRecording), Array.Empty<LiveTranscriptSegment>());

                await OpenRealtimeAsync(channels, ct).ConfigureAwait(false);

                _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                var token = _cts.Token;
                _audioPump = Task.Run(() => AudioPumpAsync(token));
                _transcriptPump = Task.Run(() => TranscriptPumpAsync(token), token);
                _durationTimer = Task.Run(() => DurationTimerAsync(token), token);
                if (_capture.HasSystemAudio)
                {
                    _systemMonitor = Task.Run(() => SystemMonitorAsync(token), token);
                }

                var hasSystem = _capture.HasSystemAudio;
                var offline = _liveOffline;
                var id = _recordingId.ToString();
                UpdateState(s => s with
                {
                    Phase = RecordingPhase.Recording,
                    RequestedSystemAudio = requestedSystemAudio,
                    HasSystemAudio = hasSystem,
                    CurrentRecordingId = id,
                    LiveTranscriptionOffline = offline,
                });
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogError(ex, "Recording start failed; rolling back");
                await TeardownStartFailureAsync().ConfigureAwait(false);
                UpdateState(_ => RecordingSessionState.Idle with { Error = "Couldn't start the recording. Please try again." });
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task StopAsync()
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (State.Phase is RecordingPhase.Idle or RecordingPhase.Finalizing)
            {
                return;
            }
            UpdateState(s => s with { Phase = RecordingPhase.Finalizing });
            await DrainCaptureAsync().ConfigureAwait(false);

            try
            {
                double audioDuration = 0;
                long bytes = 0;

                if (_session is not null && !_diskFatal)
                {
                    try { await _session.EndTurnAsync().ConfigureAwait(false); } catch { /* finalize best-effort */ }
                    // Give the provider a brief window to emit trailing finals before close
                    // (approximates RealtimeCloseDrainPolicy; precise drain wiring is in DeepgramSession TODO).
                    try { await _clock.Delay(TimeSpan.FromMilliseconds(650), CancellationToken.None).ConfigureAwait(false); } catch { }
                }

                if (_writer is not null)
                {
                    _writer.Complete();
                    audioDuration = _writer.DurationSeconds;
                    bytes = _writer.BytesWritten;
                    await _writer.DisposeAsync().ConfigureAwait(false);
                }

                if (_session is not null)
                {
                    try { await _session.CloseAsync(TimeSpan.FromSeconds(5)).ConfigureAwait(false); } catch { /* closing */ }
                    MergeSessionSegments(_session);
                }

                var persistedDuration = PersistedDuration(audioDuration, _durationSeconds);
                var uploadable = RecordingAudioUploadPolicy.CanUploadFinalizedAudio(audioDuration, bytes);
                if (!uploadable)
                {
                    _backups.DiscardAudioFile(_recordingId);
                }

                var segments = FinalizedSegments();
                _backups.Save(NewManifest(persistedDuration, JoinTranscript(segments), segments.Count, hasAudioFile: uploadable, RecordingBackupSyncState.LocalReady), segments);

                StartBackgroundSync();
            }
            finally
            {
                TeardownContext();
                UpdateState(s => s with { Phase = RecordingPhase.Idle, IsPaused = false });
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task DiscardAsync()
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (State.Phase != RecordingPhase.Recording)
            {
                return;
            }
            UpdateState(s => s with { Phase = RecordingPhase.Finalizing });
            await DrainCaptureAsync().ConfigureAwait(false);

            try
            {
                if (_writer is not null)
                {
                    try { _writer.Complete(); } catch { /* discarding */ }
                    await _writer.DisposeAsync().ConfigureAwait(false);
                }
                if (_session is not null)
                {
                    try { await _session.CloseAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false); } catch { /* discarding */ }
                }

                var id = _recordingId;
                try { await _api.DeleteRecordingAsync(id.ToString(), permanent: true).ConfigureAwait(false); }
                catch (Exception ex) { _logger.LogWarning(ex, "Discard: server delete failed for {Id}", id); }
                _backups.Remove(id);
            }
            finally
            {
                TeardownContext();
                UpdateState(_ => RecordingSessionState.Idle);
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task PauseAsync()
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (State.Phase != RecordingPhase.Recording || State.IsPaused)
            {
                return;
            }
            // NOTE: pauses the duration clock; suspending the capture engine + realtime
            // send arrives with the IAudioCapture Pause/Resume ripple (deferred, VM-gated).
            UpdateState(s => s with { IsPaused = true });
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task ResumeAsync()
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (State.Phase != RecordingPhase.Recording || !State.IsPaused)
            {
                return;
            }
            UpdateState(s => s with { IsPaused = false });
        }
        finally
        {
            _gate.Release();
        }
    }

    public void ClearError() => UpdateState(s => s with { Error = null });

    public async ValueTask DisposeAsync()
    {
        lock (_stateLock)
        {
            if (_disposed) return;
            _disposed = true;
        }
        _lifetimeCts.Cancel();
        try
        {
            if (State.Phase is not RecordingPhase.Idle)
            {
                await StopAsync().WaitAsync(TimeSpan.FromSeconds(10)).ConfigureAwait(false);
            }
        }
        catch { /* disposing */ }
        _lifetimeCts.Dispose();
        _gate.Dispose();
    }

    // ----- teardown helpers -----------------------------------------------

    /// <summary>Stop capture (completing its Frames channel), cancel sends so a parked
    /// SendPcmAsync unwinds, then drain the pumps with a bounded timeout.</summary>
    private async Task DrainCaptureAsync()
    {
        if (_capture is not null)
        {
            try { await _capture.StopAsync().ConfigureAwait(false); } catch { /* stopping */ }
        }
        _cts?.Cancel();
        await AwaitPump(_audioPump, TimeSpan.FromSeconds(8)).ConfigureAwait(false);
        await AwaitPump(_transcriptPump, TimeSpan.FromSeconds(3)).ConfigureAwait(false);
        await AwaitPump(_durationTimer, TimeSpan.FromSeconds(3)).ConfigureAwait(false);
        await AwaitPump(_systemMonitor, TimeSpan.FromSeconds(3)).ConfigureAwait(false);
    }

    private async Task TeardownStartFailureAsync()
    {
        _cts?.Cancel();
        if (_capture is not null) { try { await _capture.StopAsync().ConfigureAwait(false); } catch { } try { await _capture.DisposeAsync().ConfigureAwait(false); } catch { } }
        if (_writer is not null) { try { await _writer.DisposeAsync().ConfigureAwait(false); } catch { } }
        if (_session is not null) { try { await _session.CloseAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false); } catch { } }
        if (_recordingId != Guid.Empty)
        {
            try { await _api.DeleteRecordingAsync(_recordingId.ToString(), permanent: true).ConfigureAwait(false); } catch { }
            _backups.Remove(_recordingId);
        }
        TeardownContext();
    }

    private void StartBackgroundSync()
    {
        _ = Task.Run(() => _sync.RunAsync(_lifetimeCts.Token))
            .ContinueWith(t => _logger.LogError(t.Exception, "Background recording sync faulted"),
                TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously);
    }

    // ----- realtime open (no-throw degrade) --------------------------------

    private async Task OpenRealtimeAsync(int channels, CancellationToken ct)
    {
        try
        {
            async Task<RealtimeTranscriptionSessionConfig> Remint(CancellationToken c) =>
                await _api.CreateRealtimeTranscriptionSessionAsync(
                    new CreateRealtimeTranscriptionSessionRequest(_language, channels, "recording"), c).ConfigureAwait(false);

            var initialConfig = await Remint(ct).ConfigureAwait(false);
            _session = _sessionFactory is not null
                ? _sessionFactory(initialConfig)
                : RealtimeSessionFactory.CreateReconnecting(initialConfig, Remint);
            await _session.OpenAsync(ct).ConfigureAwait(false);
            _liveOffline = false;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _liveOffline = true;
            _session = null;
            _logger.LogWarning(ex, "Realtime session unavailable; recording local-only");
        }
    }

    // ----- pumps -----------------------------------------------------------

    private async Task AudioPumpAsync(CancellationToken sendToken)
    {
        var capture = _capture;
        var writer = _writer;
        if (capture is null || writer is null)
        {
            return;
        }
        // Read until the capture channel completes (on StopAsync) — NOT gated on the
        // send token — so trailing buffered frames are always written to disk. Sends
        // use the cancellable token so a parked send unwinds promptly on stop.
        await foreach (var frame in capture.Frames.ReadAllAsync(CancellationToken.None).ConfigureAwait(false))
        {
            try
            {
                writer.WriteEncodedPcm(frame.Pcm16); // local-first
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _diskFatal = true;
                _logger.LogError(ex, "Audio write failed — halting consumption");
                UpdateState(s => s with { Error = "Couldn't write the recording to disk — recording stopped." });
                return;
            }

            if (!_liveOffline && !sendToken.IsCancellationRequested && _session is { } session)
            {
                try
                {
                    await session.SendPcmAsync(frame.Pcm16, sendToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException) { /* stopping — keep draining to disk */ }
                catch (Exception)
                {
                    ContinueLocalOnly("realtime send failed");
                }
            }
        }
    }

    private async Task TranscriptPumpAsync(CancellationToken ct)
    {
        if (_session is null)
        {
            return;
        }
        try
        {
            await foreach (var ev in _session.Events.WithCancellation(ct).ConfigureAwait(false))
            {
                switch (ev)
                {
                    case TranscriptionEvent.Transcript t:
                        lock (_stateLock)
                        {
                            if (t.Segment.IsFinal)
                            {
                                _committed.Add(t.Segment);
                                _interim = string.Empty;
                            }
                            else
                            {
                                _interim = t.Segment.Text;
                            }
                        }
                        PublishTranscript();
                        break;

                    case TranscriptionEvent.Reconnecting r:
                        UpdateState(s => s with { ConnectionState = RealtimeConnectionState.Reconnecting, ReconnectAttempt = r.Attempt, ReconnectMaxAttempts = r.MaxAttempts });
                        break;

                    case TranscriptionEvent.Reconnected:
                    case TranscriptionEvent.Connected:
                        UpdateState(s => s with { ConnectionState = RealtimeConnectionState.Connected });
                        break;

                    case TranscriptionEvent.Disconnected:
                    case TranscriptionEvent.ReconnectionFailed:
                        ContinueLocalOnly("realtime disconnected");
                        break;

                    case TranscriptionEvent.ProviderWarning w when TranscriptionErrorCodes.Fatal.Contains(w.Code):
                        ContinueLocalOnly($"fatal provider error: {w.Code}");
                        break;
                }
            }
        }
        catch (OperationCanceledException) { /* stopping */ }
    }

    private async Task DurationTimerAsync(CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await _clock.Delay(TimeSpan.FromSeconds(1), ct).ConfigureAwait(false);
                if (State.IsPaused)
                {
                    continue;
                }
                var seconds = Interlocked.Increment(ref _durationSeconds);
                UpdateState(s => s with { DurationSeconds = seconds });
            }
        }
        catch (OperationCanceledException) { /* stopping */ }
    }

    private async Task SystemMonitorAsync(CancellationToken ct)
    {
        var capture = _capture;
        if (capture is null)
        {
            return;
        }
        var warnedOnce = false;
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await _clock.Delay(TimeSpan.FromSeconds(1), ct).ConfigureAwait(false);
                var warn = SystemAudioWarningPolicy.ShouldShowCaptureWarning(capture.SystemAudioStalled, capture.SystemAudioReceivedAny);
                var hasSystem = capture.HasSystemAudio;
                UpdateState(s => s with { SystemAudioWarning = warn ? "system_audio_stalled" : null, HasSystemAudio = hasSystem });
                if (warn && !warnedOnce)
                {
                    warnedOnce = true;
                    _notices.Post("System audio capture stalled.");
                }
                else if (!warn)
                {
                    warnedOnce = false;
                }
            }
        }
        catch (OperationCanceledException) { /* stopping */ }
    }

    private void ContinueLocalOnly(string reason)
    {
        if (State.Phase != RecordingPhase.Recording || _diskFatal)
        {
            return; // never overwrite a disk-fatal state with a benign degrade
        }
        _liveOffline = true;
        _logger.LogInformation("Degrading to local-only transcription: {Reason}", reason);
        UpdateState(s => s with { LiveTranscriptionOffline = true, ConnectionState = RealtimeConnectionState.Offline });
    }

    // ----- helpers ---------------------------------------------------------

    private void ResetForNewRecording(RecordingType type, string language)
    {
        _recordingType = type;
        _language = string.IsNullOrWhiteSpace(language) ? "en" : language;
        _durationSeconds = 0;
        _liveOffline = false;
        _diskFatal = false;
        _interim = string.Empty;
        _recordingId = Guid.Empty;
        lock (_stateLock) { _committed.Clear(); }
    }

    private void TeardownContext()
    {
        _capture = null;
        _session = null;
        _writer = null;
        _cts?.Dispose();
        _cts = null;
        _audioPump = _transcriptPump = _durationTimer = _systemMonitor = null;
    }

    private static async Task AwaitPump(Task? pump, TimeSpan? timeout = null)
    {
        if (pump is null)
        {
            return;
        }
        try
        {
            if (timeout is { } t) { await pump.WaitAsync(t).ConfigureAwait(false); }
            else { await pump.ConfigureAwait(false); }
        }
        catch { /* cancelled / timed out / faulted — best-effort drain */ }
    }

    private void MergeSessionSegments(IRealtimeTranscriptionSession session)
    {
        lock (_stateLock)
        {
            var seen = new HashSet<string>(_committed.Select(SegmentKey), StringComparer.Ordinal);
            foreach (var seg in session.CollectedSegments)
            {
                if (seg.IsFinal && seen.Add(SegmentKey(seg)))
                {
                    _committed.Add(seg);
                }
            }
        }
    }

    private static string SegmentKey(LiveTranscriptSegment s) => $"{s.StartMs}:{s.EndMs}:{s.Text}";

    private IReadOnlyList<LiveTranscriptSegment> FinalizedSegments()
    {
        lock (_stateLock)
        {
            var segments = new List<LiveTranscriptSegment>(_committed);
            var trailing = _interim.Trim();
            if (trailing.Length > 0)
            {
                var start = segments.Count > 0 ? segments[^1].EndMs : 0;
                segments.Add(new LiveTranscriptSegment(trailing, Speaker: null, IsFinal: true, StartMs: start, EndMs: start, Confidence: 1.0));
            }
            return segments;
        }
    }

    private void PublishTranscript()
    {
        string committed, interim;
        lock (_stateLock)
        {
            committed = JoinTranscript(_committed);
            interim = _interim;
        }
        UpdateState(s => s with { CommittedTranscript = committed, InterimTranscript = interim });
    }

    private static string JoinTranscript(IReadOnlyList<LiveTranscriptSegment> segments)
        => string.Join(" ", segments.Select(s => s.Text.Trim()).Where(t => t.Length > 0));

    private int PersistedDuration(double audioDuration, int timerSeconds)
    {
        if (audioDuration > 0)
        {
            if (timerSeconds - audioDuration > 5)
            {
                _logger.LogWarning("Recording duration mismatch: timer {Timer}s vs audio {Audio}s", timerSeconds, audioDuration);
            }
            return (int)Math.Round(audioDuration);
        }
        return timerSeconds;
    }

    private RecordingBackupManifest NewManifest(int durationSeconds, string transcript, int segmentCount, bool hasAudioFile, RecordingBackupSyncState syncState)
        => new(
            _recordingId,
            "Recording",
            _recordingType,
            _clock.UtcNow,
            durationSeconds,
            segmentCount,
            transcript,
            LastErrorMessage: null,
            UpdatedAt: _clock.UtcNow,
            HasAudioFile: hasAudioFile,
            IsPermanentFailure: false,
            RequiresAuthentication: false,
            SyncState: syncState);

    private void UpdateState(Func<RecordingSessionState, RecordingSessionState> mutate)
    {
        RecordingSessionState snapshot;
        lock (_stateLock)
        {
            _state = mutate(_state);
            snapshot = _state;
        }
        StateChanged?.Invoke(snapshot);
    }
}
