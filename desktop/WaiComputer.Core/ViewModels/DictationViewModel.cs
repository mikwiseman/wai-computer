using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using WaiComputer.Core.Dictation;

namespace WaiComputer.Core.ViewModels;

/// <summary>
/// Portable ViewModel that exposes the <see cref="IDictationOrchestrator"/> state
/// machine to the Windows (WinUI) and Linux (Avalonia) dictation surfaces. Maps the
/// orchestrator's background-thread events onto bindable properties (marshalled
/// through <see cref="IUiDispatcher"/>) and wraps start/stop/cancel as commands.
/// </summary>
public sealed partial class DictationViewModel : ObservableObject, IDisposable
{
    private const string ClipboardPasteNotice = "Your text is on the clipboard — paste it where you need it.";

    private readonly IDictationOrchestrator _orchestrator;
    private readonly DictationLanguageStore _languageStore;
    private readonly IUiDispatcher _dispatcher;

    [ObservableProperty] private DictationState _state = DictationState.Idle;
    [ObservableProperty] private string _liveTranscript = string.Empty;
    [ObservableProperty] private string? _lastInsertedText;
    [ObservableProperty] private string? _errorMessage;
    [ObservableProperty] private string? _recoveryNotice;

    public IAsyncRelayCommand StartCommand { get; }
    public IAsyncRelayCommand StopCommand { get; }
    public IAsyncRelayCommand CancelCommand { get; }

    public DictationViewModel(IDictationOrchestrator orchestrator, DictationLanguageStore languageStore, IUiDispatcher? dispatcher = null)
    {
        _orchestrator = orchestrator;
        _languageStore = languageStore;
        _dispatcher = dispatcher ?? new ImmediateUiDispatcher();

        _orchestrator.StateChanged += HandleStateChanged;
        _orchestrator.InterimTranscriptUpdated += HandleInterim;
        _orchestrator.Completed += HandleCompleted;
        _orchestrator.ClipboardRecoveryRequired += HandleRecovery;
        _orchestrator.Failed += HandleFailed;

        StartCommand = new AsyncRelayCommand(StartAsync, () => IsIdle);
        StopCommand = new AsyncRelayCommand(() => _orchestrator.StopAndInsertAsync(CancellationToken.None), () => IsListening);
        CancelCommand = new AsyncRelayCommand(() => _orchestrator.CancelAsync(CancellationToken.None), () => !IsIdle);

        _state = _orchestrator.State;
    }

    public bool IsIdle => State == DictationState.Idle;
    public bool IsListening => State == DictationState.Listening;
    public bool IsBusy => State is DictationState.Connecting or DictationState.Processing or DictationState.Inserting;

    public IReadOnlyList<DictationLanguage> AvailableLanguages => DictationLanguageCatalog.All;
    public bool IsAutoDetectLanguage => _languageStore.IsAutoDetect;
    public IReadOnlySet<string> SelectedLanguages => _languageStore.SelectedLanguages;

    /// <summary>Clears the previous turn's surface and begins a new dictation.</summary>
    public async Task StartAsync()
    {
        _dispatcher.Post(() =>
        {
            ErrorMessage = null;
            RecoveryNotice = null;
            LastInsertedText = null;
            LiveTranscript = string.Empty;
        });
        await _orchestrator.StartAsync(CancellationToken.None).ConfigureAwait(false);
    }

    /// <summary>Toggle a dictation language; a language change invalidates the prefetched config.</summary>
    public void ToggleLanguage(string code)
    {
        _languageStore.Toggle(code);
        _orchestrator.ClearConfigCache();
        RaiseLanguageChanged();
    }

    public void SetAutoDetectLanguage()
    {
        _languageStore.SetAutoDetect();
        _orchestrator.ClearConfigCache();
        RaiseLanguageChanged();
    }

    // The CommunityToolkit source generator calls this when State changes.
    partial void OnStateChanged(DictationState value)
    {
        OnPropertyChanged(nameof(IsIdle));
        OnPropertyChanged(nameof(IsListening));
        OnPropertyChanged(nameof(IsBusy));
        StartCommand.NotifyCanExecuteChanged();
        StopCommand.NotifyCanExecuteChanged();
        CancelCommand.NotifyCanExecuteChanged();
    }

    private void HandleStateChanged(DictationState s) => _dispatcher.Post(() => State = s);

    private void HandleInterim(string text) => _dispatcher.Post(() => LiveTranscript = text);

    private void HandleCompleted(DictationResult result) => _dispatcher.Post(() =>
    {
        LastInsertedText = result.InsertedText;
        LiveTranscript = string.Empty;
        ErrorMessage = null;
        RecoveryNotice = result.InsertedViaClipboard ? ClipboardPasteNotice : null;
    });

    private void HandleRecovery(string _) => _dispatcher.Post(() => RecoveryNotice = ClipboardPasteNotice);

    private void HandleFailed(string message) => _dispatcher.Post(() => ErrorMessage = message);

    private void RaiseLanguageChanged()
    {
        OnPropertyChanged(nameof(IsAutoDetectLanguage));
        OnPropertyChanged(nameof(SelectedLanguages));
    }

    public void Dispose()
    {
        _orchestrator.StateChanged -= HandleStateChanged;
        _orchestrator.InterimTranscriptUpdated -= HandleInterim;
        _orchestrator.Completed -= HandleCompleted;
        _orchestrator.ClipboardRecoveryRequired -= HandleRecovery;
        _orchestrator.Failed -= HandleFailed;
    }
}
