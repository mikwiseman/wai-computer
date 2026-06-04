using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.ViewModels;

/// <summary>
/// Portable user-settings ViewModel shared by the Windows (WinUI) and Linux
/// (Avalonia) settings surfaces. Binds <see cref="IApiClient.GetSettingsAsync"/>
/// for load and <see cref="IApiClient.UpdateSettingsAsync"/> for save, mirroring
/// every field of <see cref="UserSettings"/> as an editable observable property.
/// <see cref="LoadAsync"/> populates the props from the server; <see cref="SaveCommand"/>
/// builds an <see cref="UpdateSettingsRequest"/> from the current props, PATCHes it,
/// and refreshes from the response. Errors surface on <see cref="ErrorMessage"/> —
/// no silent degradation, no fabricated defaults that mask a failure.
/// </summary>
public sealed partial class SettingsViewModel : ObservableObject
{
    private readonly IApiClient _api;
    private readonly ILogger<SettingsViewModel> _logger;

    // Snapshot of the last loaded/saved server state, used to compute HasChanges
    // and to rebuild the full UpdateSettingsRequest from the current props.
    private UserSettings? _loaded;

    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private bool _isSaving;
    [ObservableProperty] private string? _errorMessage;
    [ObservableProperty] private bool _hasChanges;

    [ObservableProperty] private string _defaultLanguage = string.Empty;
    [ObservableProperty] private string _summaryLanguage = string.Empty;
    [ObservableProperty] private SummaryStyle _summaryStyle = SummaryStyle.Medium;
    [ObservableProperty] private string _dictationLiveSttProvider = string.Empty;
    [ObservableProperty] private string _dictationLiveSttModel = string.Empty;
    [ObservableProperty] private string _recordingLiveSttProvider = string.Empty;
    [ObservableProperty] private string _recordingLiveSttModel = string.Empty;
    [ObservableProperty] private string _fileSttProvider = string.Empty;
    [ObservableProperty] private string _fileSttModel = string.Empty;
    [ObservableProperty] private bool _dictationPostFilterEnabled;
    [ObservableProperty] private string? _dictationPostFilterProvider;
    [ObservableProperty] private string? _dictationPostFilterModel;

    public IAsyncRelayCommand LoadCommand { get; }
    public IAsyncRelayCommand SaveCommand { get; }

    public SettingsViewModel(IApiClient api, ILogger<SettingsViewModel>? logger = null)
    {
        _api = api;
        _logger = logger ?? NullLogger<SettingsViewModel>.Instance;

        LoadCommand = new AsyncRelayCommand(() => LoadAsync(CancellationToken.None), () => !IsLoading && !IsSaving);
        SaveCommand = new AsyncRelayCommand(() => SaveAsync(CancellationToken.None), () => CanSave);
    }

    /// <summary>True once settings have loaded at least once.</summary>
    public bool IsLoaded => _loaded is not null;

    /// <summary>Save is allowed only when loaded, not busy, and there are pending edits.</summary>
    public bool CanSave => IsLoaded && !IsLoading && !IsSaving && HasChanges;

    /// <summary>Fetch the user's settings and populate the editable properties.</summary>
    public async Task LoadAsync(CancellationToken ct = default)
    {
        if (IsLoading || IsSaving)
        {
            return;
        }

        IsLoading = true;
        ErrorMessage = null;
        try
        {
            var settings = await _api.GetSettingsAsync(ct).ConfigureAwait(false);
            ApplySettings(settings);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Loading settings failed");
            ErrorMessage = "Couldn't load your settings. Try again.";
        }
        finally
        {
            IsLoading = false;
        }
    }

    /// <summary>Persist the current edits, then refresh from the server response.</summary>
    public async Task SaveAsync(CancellationToken ct = default)
    {
        if (IsLoading || IsSaving)
        {
            return;
        }
        if (_loaded is null)
        {
            // Never invent a payload before a real load — surface the misuse instead of masking it.
            ErrorMessage = "Load your settings before saving.";
            return;
        }

        IsSaving = true;
        ErrorMessage = null;
        try
        {
            var request = BuildRequest();
            var updated = await _api.UpdateSettingsAsync(request, ct).ConfigureAwait(false);
            ApplySettings(updated);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Saving settings failed");
            ErrorMessage = "Couldn't save your settings. Try again.";
        }
        finally
        {
            IsSaving = false;
        }
    }

    /// <summary>Discard unsaved edits, restoring the last loaded/saved server state.</summary>
    public void ResetChanges()
    {
        if (_loaded is not null)
        {
            ApplySettings(_loaded);
        }
    }

    private void ApplySettings(UserSettings settings)
    {
        _loaded = settings;
        DefaultLanguage = settings.DefaultLanguage;
        SummaryLanguage = settings.SummaryLanguage;
        SummaryStyle = settings.SummaryStyle;
        DictationLiveSttProvider = settings.DictationLiveSttProvider;
        DictationLiveSttModel = settings.DictationLiveSttModel;
        RecordingLiveSttProvider = settings.RecordingLiveSttProvider;
        RecordingLiveSttModel = settings.RecordingLiveSttModel;
        FileSttProvider = settings.FileSttProvider;
        FileSttModel = settings.FileSttModel;
        DictationPostFilterEnabled = settings.DictationPostFilterEnabled;
        DictationPostFilterProvider = settings.DictationPostFilterProvider;
        DictationPostFilterModel = settings.DictationPostFilterModel;
        OnPropertyChanged(nameof(IsLoaded));
        RecomputeHasChanges();
    }

    private UpdateSettingsRequest BuildRequest() => new(
        DefaultLanguage: DefaultLanguage,
        SummaryLanguage: SummaryLanguage,
        SummaryStyle: SummaryStyle,
        DictationLiveSttProvider: DictationLiveSttProvider,
        DictationLiveSttModel: DictationLiveSttModel,
        RecordingLiveSttProvider: RecordingLiveSttProvider,
        RecordingLiveSttModel: RecordingLiveSttModel,
        FileSttProvider: FileSttProvider,
        FileSttModel: FileSttModel,
        DictationPostFilterEnabled: DictationPostFilterEnabled,
        DictationPostFilterProvider: DictationPostFilterProvider,
        DictationPostFilterModel: DictationPostFilterModel);

    private void RecomputeHasChanges()
    {
        var loaded = _loaded;
        HasChanges = loaded is not null && (
            DefaultLanguage != loaded.DefaultLanguage ||
            SummaryLanguage != loaded.SummaryLanguage ||
            SummaryStyle != loaded.SummaryStyle ||
            DictationLiveSttProvider != loaded.DictationLiveSttProvider ||
            DictationLiveSttModel != loaded.DictationLiveSttModel ||
            RecordingLiveSttProvider != loaded.RecordingLiveSttProvider ||
            RecordingLiveSttModel != loaded.RecordingLiveSttModel ||
            FileSttProvider != loaded.FileSttProvider ||
            FileSttModel != loaded.FileSttModel ||
            DictationPostFilterEnabled != loaded.DictationPostFilterEnabled ||
            DictationPostFilterProvider != loaded.DictationPostFilterProvider ||
            DictationPostFilterModel != loaded.DictationPostFilterModel);
    }

    // ----- CommunityToolkit source-generated change hooks -------------------

    partial void OnIsLoadingChanged(bool value)
    {
        LoadCommand.NotifyCanExecuteChanged();
        SaveCommand.NotifyCanExecuteChanged();
        OnPropertyChanged(nameof(CanSave));
    }

    partial void OnIsSavingChanged(bool value)
    {
        LoadCommand.NotifyCanExecuteChanged();
        SaveCommand.NotifyCanExecuteChanged();
        OnPropertyChanged(nameof(CanSave));
    }

    partial void OnHasChangesChanged(bool value)
    {
        SaveCommand.NotifyCanExecuteChanged();
        OnPropertyChanged(nameof(CanSave));
    }

    partial void OnDefaultLanguageChanged(string value) => RecomputeHasChanges();
    partial void OnSummaryLanguageChanged(string value) => RecomputeHasChanges();
    partial void OnSummaryStyleChanged(SummaryStyle value) => RecomputeHasChanges();
    partial void OnDictationLiveSttProviderChanged(string value) => RecomputeHasChanges();
    partial void OnDictationLiveSttModelChanged(string value) => RecomputeHasChanges();
    partial void OnRecordingLiveSttProviderChanged(string value) => RecomputeHasChanges();
    partial void OnRecordingLiveSttModelChanged(string value) => RecomputeHasChanges();
    partial void OnFileSttProviderChanged(string value) => RecomputeHasChanges();
    partial void OnFileSttModelChanged(string value) => RecomputeHasChanges();
    partial void OnDictationPostFilterEnabledChanged(bool value) => RecomputeHasChanges();
    partial void OnDictationPostFilterProviderChanged(string? value) => RecomputeHasChanges();
    partial void OnDictationPostFilterModelChanged(string? value) => RecomputeHasChanges();
}
