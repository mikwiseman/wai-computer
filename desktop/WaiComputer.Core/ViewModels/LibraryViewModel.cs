using System.Collections.ObjectModel;
using System.Linq;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.ViewModels;

/// <summary>
/// Portable recordings-library ViewModel shared by the Windows (WinUI) and Linux
/// (Avalonia) clients. Binds <see cref="IApiClient.ListRecordingsAsync"/> (with the
/// starred/type/folder/trashed filters), <see cref="IApiClient.ListFoldersAsync"/>,
/// and the bulk operation (<see cref="BulkRecordingAction"/> delete|restore|move).
/// Multi-select drives the bulk commands. Failures surface on
/// <see cref="ErrorMessage"/> — never swallowed, never masked as an empty list.
/// </summary>
public sealed partial class LibraryViewModel : ObservableObject
{
    private const int PageSize = 50;

    private readonly IApiClient _api;
    private readonly ILogger<LibraryViewModel> _logger;

    [ObservableProperty] private RecordingType? _filterType;
    [ObservableProperty] private string? _filterFolderId;
    [ObservableProperty] private bool _showStarredOnly;
    [ObservableProperty] private bool _showTrashed;
    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private string? _errorMessage;

    public ObservableCollection<Recording> Recordings { get; } = new();
    public ObservableCollection<Folder> Folders { get; } = new();
    public ObservableCollection<string> SelectedIds { get; } = new();

    public IAsyncRelayCommand RefreshCommand { get; }
    public IAsyncRelayCommand TrashSelectedCommand { get; }
    public IAsyncRelayCommand RestoreSelectedCommand { get; }

    public LibraryViewModel(IApiClient api, ILogger<LibraryViewModel>? logger = null)
    {
        _api = api;
        _logger = logger ?? NullLogger<LibraryViewModel>.Instance;

        RefreshCommand = new AsyncRelayCommand(() => LoadAsync(CancellationToken.None));
        TrashSelectedCommand = new AsyncRelayCommand(() => BulkAsync(BulkRecordingAction.Delete, null, CancellationToken.None), HasSelection);
        RestoreSelectedCommand = new AsyncRelayCommand(() => BulkAsync(BulkRecordingAction.Restore, null, CancellationToken.None), HasSelection);

        SelectedIds.CollectionChanged += (_, _) =>
        {
            TrashSelectedCommand.NotifyCanExecuteChanged();
            RestoreSelectedCommand.NotifyCanExecuteChanged();
        };
    }

    private bool HasSelection() => SelectedIds.Count > 0;

    /// <summary>Toggle a recording's membership in the multi-select set.</summary>
    public void ToggleSelection(string recordingId)
    {
        if (!SelectedIds.Remove(recordingId))
        {
            SelectedIds.Add(recordingId);
        }
    }

    /// <summary>Loads recordings for the current filters plus the folder list.</summary>
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
            var starred = ShowStarredOnly ? true : (bool?)null;
            var recordings = await _api.ListRecordingsAsync(0, PageSize, starred, FilterType, FilterFolderId, ShowTrashed, ct).ConfigureAwait(false);
            Recordings.Clear();
            foreach (var recording in recordings)
            {
                Recordings.Add(recording);
            }

            var folders = await _api.ListFoldersAsync(ct).ConfigureAwait(false);
            Folders.Clear();
            foreach (var folder in folders)
            {
                Folders.Add(folder);
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Loading the library failed");
            ErrorMessage = "Couldn't load your recordings. Try again.";
        }
        finally
        {
            IsLoading = false;
        }
    }

    /// <summary>Move the selected recordings to a folder (or to the root with a null id).</summary>
    public Task MoveSelectedToFolderAsync(string? folderId, CancellationToken ct = default)
        => BulkAsync(BulkRecordingAction.Move, folderId, ct);

    /// <summary>
    /// Applies a bulk action to the selected recordings, then reloads. On outright
    /// failure the selection is preserved for retry and no reload is issued; a
    /// partial failure (some items failed server-side) is surfaced after the reload.
    /// </summary>
    public async Task BulkAsync(BulkRecordingAction action, string? folderId, CancellationToken ct = default)
    {
        if (SelectedIds.Count == 0)
        {
            return;
        }
        ErrorMessage = null;
        int failed;
        try
        {
            var request = new BulkRecordingOperationRequest(SelectedIds.ToList(), action, folderId);
            var result = await _api.BulkRecordingOperationAsync(request, ct).ConfigureAwait(false);
            failed = result.Failed;
            SelectedIds.Clear();
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Bulk recording operation failed");
            ErrorMessage = "Couldn't apply the bulk action. Try again.";
            return; // keep the selection so the user can retry; don't reload
        }

        await LoadAsync(ct).ConfigureAwait(false);
        if (failed > 0 && ErrorMessage is null)
        {
            ErrorMessage = $"{failed} item(s) couldn't be updated.";
        }
    }
}
