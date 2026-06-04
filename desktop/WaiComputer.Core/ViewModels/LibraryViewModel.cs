using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.ViewModels;

/// <summary>
/// Portable ViewModel for the recordings library surface shared by the Windows
/// (WinUI) and Linux (Avalonia) shells. Loads recordings + folders, holds the
/// current filter state (type / folder / starred / trash), tracks a multi-select
/// set, and runs bulk operations (delete / restore / move) through
/// <see cref="IApiClient.BulkRecordingOperationAsync"/>, re-loading afterwards.
///
/// Request/response only — no background-thread events, so no <c>IUiDispatcher</c>.
/// Failures surface on <see cref="ErrorMessage"/>; nothing is silently swallowed
/// and no fabricated defaults mask a failed call.
/// </summary>
public sealed partial class LibraryViewModel : ObservableObject
{
    private const int PageSize = 50;

    private readonly IApiClient _api;
    private readonly ILogger<LibraryViewModel> _logger;

    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private string? _errorMessage;

    // ----- filter state -----------------------------------------------------
    // Setters only mutate state; a load is an explicit action (LoadAsync /
    // RefreshCommand / the filter helpers below) so two-way XAML bindings don't
    // fire a network request on every intermediate change.
    [ObservableProperty] private RecordingType? _filterType;
    [ObservableProperty] private string? _folderId;
    [ObservableProperty] private bool _showStarredOnly;
    [ObservableProperty] private bool _showTrashed;

    /// <summary>Recordings for the current filter, newest-first as the API returns them.</summary>
    public ObservableCollection<Recording> Recordings { get; } = new();

    /// <summary>The user's folders, for the sidebar / move target picker.</summary>
    public ObservableCollection<Folder> Folders { get; } = new();

    /// <summary>Currently multi-selected recording ids (the bulk-operation set).</summary>
    public ObservableCollection<string> SelectedIds { get; } = new();

    public IAsyncRelayCommand RefreshCommand { get; }

    /// <summary>Soft-delete (move to trash) the current selection, then reload.</summary>
    public IAsyncRelayCommand BulkTrashCommand { get; }

    /// <summary>Restore the current selection out of the trash, then reload.</summary>
    public IAsyncRelayCommand BulkRestoreCommand { get; }

    public LibraryViewModel(IApiClient api, ILogger<LibraryViewModel>? logger = null)
    {
        _api = api;
        _logger = logger ?? NullLogger<LibraryViewModel>.Instance;

        RefreshCommand = new AsyncRelayCommand(() => LoadAsync(CancellationToken.None));
        BulkTrashCommand = new AsyncRelayCommand(
            () => RunBulkAsync(BulkRecordingAction.Delete, folderId: null, CancellationToken.None),
            () => HasSelection);
        BulkRestoreCommand = new AsyncRelayCommand(
            () => RunBulkAsync(BulkRecordingAction.Restore, folderId: null, CancellationToken.None),
            () => HasSelection);

        SelectedIds.CollectionChanged += (_, _) =>
        {
            OnPropertyChanged(nameof(HasSelection));
            OnPropertyChanged(nameof(SelectionCount));
            BulkTrashCommand.NotifyCanExecuteChanged();
            BulkRestoreCommand.NotifyCanExecuteChanged();
        };
    }

    public bool HasSelection => SelectedIds.Count > 0;
    public int SelectionCount => SelectedIds.Count;

    /// <summary>Load folders + recordings for the current filter state.</summary>
    public async Task LoadAsync(CancellationToken ct = default)
    {
        IsLoading = true;
        ErrorMessage = null;
        try
        {
            var folders = await _api.ListFoldersAsync(ct).ConfigureAwait(false);
            var recordings = await _api.ListRecordingsAsync(
                skip: 0,
                limit: PageSize,
                starred: ShowStarredOnly ? true : null,
                type: FilterType,
                folderId: FolderId,
                trashed: ShowTrashed,
                ct).ConfigureAwait(false);

            ReplaceAll(Folders, folders);
            ReplaceAll(Recordings, recordings);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Loading library failed");
            ErrorMessage = "Couldn't load your recordings. Try again.";
        }
        finally
        {
            IsLoading = false;
        }
    }

    // ----- multi-select -----------------------------------------------------

    /// <summary>Add the id to the selection if absent, otherwise remove it.</summary>
    public void ToggleSelection(string recordingId)
    {
        if (!SelectedIds.Remove(recordingId))
        {
            SelectedIds.Add(recordingId);
        }
    }

    public bool IsSelected(string recordingId) => SelectedIds.Contains(recordingId);

    public void ClearSelection() => SelectedIds.Clear();

    /// <summary>Select every currently loaded recording.</summary>
    public void SelectAll()
    {
        SelectedIds.Clear();
        foreach (var r in Recordings)
        {
            SelectedIds.Add(r.Id);
        }
    }

    // ----- filter helpers (mutate state + reload) ---------------------------

    public Task SetFolderAsync(string? folderId, CancellationToken ct = default)
    {
        FolderId = folderId;
        ShowTrashed = false;
        return LoadAsync(ct);
    }

    public Task SetTypeFilterAsync(RecordingType? type, CancellationToken ct = default)
    {
        FilterType = type;
        return LoadAsync(ct);
    }

    public Task SetStarredOnlyAsync(bool starredOnly, CancellationToken ct = default)
    {
        ShowStarredOnly = starredOnly;
        return LoadAsync(ct);
    }

    public Task ShowTrashAsync(CancellationToken ct = default)
    {
        ShowTrashed = true;
        FolderId = null;
        ShowStarredOnly = false;
        return LoadAsync(ct);
    }

    // ----- bulk operations --------------------------------------------------

    /// <summary>Move the current selection into <paramref name="folderId"/> (null = no folder), then reload.</summary>
    public Task BulkMoveAsync(string? folderId, CancellationToken ct = default)
        => RunBulkAsync(BulkRecordingAction.Move, folderId, ct);

    private async Task RunBulkAsync(BulkRecordingAction action, string? folderId, CancellationToken ct)
    {
        if (SelectedIds.Count == 0)
        {
            return;
        }

        IsLoading = true;
        ErrorMessage = null;
        string? partialFailure;
        try
        {
            var request = new BulkRecordingOperationRequest(
                RecordingIds: SelectedIds.ToList(),
                Action: action,
                FolderId: folderId);
            var result = await _api.BulkRecordingOperationAsync(request, ct).ConfigureAwait(false);

            // A partial failure is not an exception; capture it so it survives the reload below.
            partialFailure = result.Failed > 0
                ? (result.Processed > 0
                    ? $"{result.Processed} updated, {result.Failed} failed."
                    : $"Operation failed for {result.Failed} recording(s).")
                : null;

            SelectedIds.Clear();
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Bulk recording operation failed");
            ErrorMessage = "That action couldn't be completed. Try again.";
            IsLoading = false;
            return;
        }

        // Re-query so the list reflects the server's post-operation state.
        await LoadAsync(ct).ConfigureAwait(false);

        // LoadAsync clears ErrorMessage on entry; re-surface the partial failure
        // afterwards so it is not silently dropped (unless the reload itself failed).
        if (partialFailure is not null && ErrorMessage is null)
        {
            ErrorMessage = partialFailure;
        }
    }

    private static void ReplaceAll<T>(ObservableCollection<T> target, IReadOnlyList<T> source)
    {
        target.Clear();
        foreach (var item in source)
        {
            target.Add(item);
        }
    }
}
