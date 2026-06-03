using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Recordings;

namespace WaiComputer.Core.ViewModels;

/// <summary>
/// Portable ViewModel exposing the <see cref="IRecordingSession"/> orchestrator to
/// the Windows (WinUI) and Linux (Avalonia) recording surfaces. The session raises
/// <see cref="IRecordingSession.StateChanged"/> from background capture/transcription
/// pump threads, so each snapshot is marshalled onto the UI thread via
/// <see cref="IUiDispatcher"/>. Start options (type / input source / language /
/// folder) are bindable; start/stop/pause/discard are commands gated by the live
/// phase. Errors surface via <see cref="ErrorMessage"/> (sourced from the session
/// state — no separate swallow path).
/// </summary>
public sealed partial class RecordingViewModel : ObservableObject, IDisposable
{
    private readonly IRecordingSession _session;
    private readonly IUiDispatcher _dispatcher;

    [ObservableProperty] private RecordingSessionState _state = RecordingSessionState.Idle;

    // Start options.
    [ObservableProperty] private RecordingType _recordingType = RecordingType.Meeting;
    [ObservableProperty] private RecordingInputSource _inputSource = RecordingInputSource.Dual;
    [ObservableProperty] private string _language = "en";
    [ObservableProperty] private string? _folderId;

    public IAsyncRelayCommand StartCommand { get; }
    public IAsyncRelayCommand StopCommand { get; }
    public IAsyncRelayCommand PauseResumeCommand { get; }
    public IAsyncRelayCommand DiscardCommand { get; }
    public IRelayCommand ClearErrorCommand { get; }

    public RecordingViewModel(IRecordingSession session, IUiDispatcher? dispatcher = null)
    {
        _session = session;
        _dispatcher = dispatcher ?? new ImmediateUiDispatcher();
        _session.StateChanged += HandleStateChanged;

        StartCommand = new AsyncRelayCommand(StartAsync, () => IsIdle);
        StopCommand = new AsyncRelayCommand(() => _session.StopAsync(), () => IsRecording);
        PauseResumeCommand = new AsyncRelayCommand(TogglePauseAsync, () => IsRecording);
        DiscardCommand = new AsyncRelayCommand(() => _session.DiscardAsync(), () => IsActive);
        ClearErrorCommand = new RelayCommand(_session.ClearError, () => ErrorMessage is not null);

        _state = _session.State;
    }

    // ----- derived view of the current snapshot -----------------------------

    public RecordingPhase Phase => State.Phase;
    public bool IsIdle => State.Phase == RecordingPhase.Idle;
    public bool IsRecording => State.Phase == RecordingPhase.Recording;
    public bool IsActive => State.Phase is RecordingPhase.Preparing or RecordingPhase.Recording or RecordingPhase.Finalizing;
    public bool IsPaused => State.IsPaused;
    public int DurationSeconds => State.DurationSeconds;
    public string CommittedTranscript => State.CommittedTranscript;
    public string InterimTranscript => State.InterimTranscript;
    public bool LiveTranscriptionOffline => State.LiveTranscriptionOffline;
    public RealtimeConnectionState ConnectionState => State.ConnectionState;
    public string? SystemAudioWarning => State.SystemAudioWarning;
    public SystemAudioHeaderIndicator HeaderIndicator => State.HeaderIndicator;
    public string? CurrentRecordingId => State.CurrentRecordingId;
    public string? ErrorMessage => State.Error;

    private async Task StartAsync()
        => await _session.StartAsync(RecordingType, InputSource, Language, FolderId, CancellationToken.None).ConfigureAwait(false);

    private async Task TogglePauseAsync()
    {
        if (IsPaused)
        {
            await _session.ResumeAsync().ConfigureAwait(false);
        }
        else
        {
            await _session.PauseAsync().ConfigureAwait(false);
        }
    }

    private void HandleStateChanged(RecordingSessionState snapshot) => _dispatcher.Post(() => State = snapshot);

    // The CommunityToolkit source generator calls this when State changes.
    partial void OnStateChanged(RecordingSessionState value)
    {
        OnPropertyChanged(string.Empty); // refresh every derived getter
        StartCommand.NotifyCanExecuteChanged();
        StopCommand.NotifyCanExecuteChanged();
        PauseResumeCommand.NotifyCanExecuteChanged();
        DiscardCommand.NotifyCanExecuteChanged();
        ClearErrorCommand.NotifyCanExecuteChanged();
    }

    public void Dispose() => _session.StateChanged -= HandleStateChanged;
}
