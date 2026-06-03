using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.ViewModels;

/// <summary>
/// Portable user-settings ViewModel shared by the Windows (WinUI) and Linux
/// (Avalonia) clients. Exposes only the user-editable, NON-managed settings
/// (default/summary language, summary style, dictation post-filter). The six
/// transcription-provider/model fields are managed by the server and the backend
/// returns HTTP 400 on any PATCH that includes them, so they are deliberately not
/// editable here. Save sends a SPARSE <see cref="UpdateSettingsRequest"/> — only
/// the fields the user actually changed — mirroring the macOS sparse-PATCH
/// contract. Failures surface on <see cref="ErrorMessage"/>; edits are preserved
/// on a failed save (no silent loss).
/// </summary>
public sealed partial class SettingsViewModel : ObservableObject
{
    private readonly IApiClient _api;
    private readonly ILogger<SettingsViewModel> _logger;
    private UserSettings? _loaded;

    [ObservableProperty] [NotifyPropertyChangedFor(nameof(HasChanges))] private string _defaultLanguage = string.Empty;
    [ObservableProperty] [NotifyPropertyChangedFor(nameof(HasChanges))] private string _summaryLanguage = string.Empty;
    [ObservableProperty] [NotifyPropertyChangedFor(nameof(HasChanges))] private SummaryStyle _summaryStyle = SummaryStyle.Medium;
    [ObservableProperty] [NotifyPropertyChangedFor(nameof(HasChanges))] private bool _dictationPostFilterEnabled;

    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private bool _isSaving;
    [ObservableProperty] private string? _errorMessage;

    public IAsyncRelayCommand SaveCommand { get; }

    public SettingsViewModel(IApiClient api, ILogger<SettingsViewModel>? logger = null)
    {
        _api = api;
        _logger = logger ?? NullLogger<SettingsViewModel>.Instance;
        SaveCommand = new AsyncRelayCommand(() => SaveAsync(CancellationToken.None), () => HasChanges && !IsSaving);
    }

    /// <summary>True when an editable field differs from the last loaded/saved snapshot.</summary>
    public bool HasChanges =>
        _loaded is not null && (
            DefaultLanguage != _loaded.DefaultLanguage ||
            SummaryLanguage != _loaded.SummaryLanguage ||
            SummaryStyle != _loaded.SummaryStyle ||
            DictationPostFilterEnabled != _loaded.DictationPostFilterEnabled);

    public async Task LoadAsync(CancellationToken ct = default)
    {
        if (IsLoading)
        {
            return;
        }
        IsLoading = true;
        ErrorMessage = null;
        try
        {
            var settings = await _api.GetSettingsAsync(ct).ConfigureAwait(false);
            ApplyLoaded(settings);
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

    public async Task SaveAsync(CancellationToken ct = default)
    {
        if (IsSaving || _loaded is null || !HasChanges)
        {
            return;
        }
        IsSaving = true;
        ErrorMessage = null;
        try
        {
            // Sparse PATCH: only the changed, non-managed fields. The six managed STT
            // provider/model fields are left null (WhenWritingNull omits them), so the
            // backend's managed-field guard never trips.
            var request = new UpdateSettingsRequest(
                DefaultLanguage: DefaultLanguage != _loaded.DefaultLanguage ? DefaultLanguage : null,
                SummaryLanguage: SummaryLanguage != _loaded.SummaryLanguage ? SummaryLanguage : null,
                SummaryStyle: SummaryStyle != _loaded.SummaryStyle ? SummaryStyle : null,
                DictationPostFilterEnabled: DictationPostFilterEnabled != _loaded.DictationPostFilterEnabled ? DictationPostFilterEnabled : null);

            var updated = await _api.UpdateSettingsAsync(request, ct).ConfigureAwait(false);
            ApplyLoaded(updated);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            // Keep the user's edits so they can retry; surface the failure.
            _logger.LogWarning(ex, "Saving settings failed");
            ErrorMessage = "Couldn't save your settings. Try again.";
        }
        finally
        {
            IsSaving = false;
        }
    }

    private void ApplyLoaded(UserSettings settings)
    {
        _loaded = settings;
        DefaultLanguage = settings.DefaultLanguage;
        SummaryLanguage = settings.SummaryLanguage;
        SummaryStyle = settings.SummaryStyle;
        DictationPostFilterEnabled = settings.DictationPostFilterEnabled;
        OnPropertyChanged(nameof(HasChanges));
        SaveCommand.NotifyCanExecuteChanged();
    }

    partial void OnDefaultLanguageChanged(string value) => SaveCommand.NotifyCanExecuteChanged();
    partial void OnSummaryLanguageChanged(string value) => SaveCommand.NotifyCanExecuteChanged();
    partial void OnSummaryStyleChanged(SummaryStyle value) => SaveCommand.NotifyCanExecuteChanged();
    partial void OnDictationPostFilterEnabledChanged(bool value) => SaveCommand.NotifyCanExecuteChanged();
    partial void OnIsSavingChanged(bool value) => SaveCommand.NotifyCanExecuteChanged();
}
