using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.ViewModels;

/// <summary>
/// Portable ViewModel for the extracted tasks / action-items surface, shared by the
/// Windows (WinUI) and Linux (Avalonia) shells. Wraps
/// <see cref="IApiClient.ListActionItemsAsync"/> (optionally filtered by
/// <see cref="StatusFilter"/> / <see cref="PriorityFilter"/>),
/// <see cref="IApiClient.UpdateActionItemAsync"/> (advance an item's status), and
/// <see cref="IApiClient.DeleteActionItemAsync"/>. This is a request/response VM with
/// no background-thread events, so it does not need an <c>IUiDispatcher</c>.
///
/// Both mutations re-sync local state from the server response (update replaces the
/// item in <see cref="Items"/>; delete removes it). Any failure surfaces on
/// <see cref="ErrorMessage"/> and leaves the existing list untouched — no silent
/// fallback, no fabricated defaults that would mask the failure.
/// </summary>
public sealed partial class ActionItemsViewModel : ObservableObject
{
    private readonly IApiClient _api;
    private readonly ILogger<ActionItemsViewModel> _logger;

    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private string? _errorMessage;
    [ObservableProperty] private ActionItemStatus? _statusFilter;
    [ObservableProperty] private ActionItemPriority? _priorityFilter;

    /// <summary>The loaded action items, in the server's order.</summary>
    public ObservableCollection<ActionItem> Items { get; } = new();

    public IAsyncRelayCommand LoadCommand { get; }
    public IAsyncRelayCommand<ActionItem> ToggleStatusCommand { get; }
    public IAsyncRelayCommand<ActionItem> DeleteCommand { get; }

    public ActionItemsViewModel(IApiClient api, ILogger<ActionItemsViewModel>? logger = null)
    {
        _api = api;
        _logger = logger ?? NullLogger<ActionItemsViewModel>.Instance;

        LoadCommand = new AsyncRelayCommand(() => LoadAsync(CancellationToken.None), () => !IsLoading);
        ToggleStatusCommand = new AsyncRelayCommand<ActionItem>(
            item => ToggleStatusAsync(item!, CancellationToken.None),
            item => item is not null && !IsLoading);
        DeleteCommand = new AsyncRelayCommand<ActionItem>(
            item => DeleteAsync(item!, CancellationToken.None),
            item => item is not null && !IsLoading);
    }

    public bool HasItems => Items.Count > 0;

    /// <summary>
    /// Load action items using the current <see cref="StatusFilter"/> /
    /// <see cref="PriorityFilter"/>. Replaces <see cref="Items"/> on success; on
    /// failure leaves the prior list intact and surfaces <see cref="ErrorMessage"/>.
    /// </summary>
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
            var items = await _api.ListActionItemsAsync(StatusFilter, PriorityFilter, ct).ConfigureAwait(false);
            Items.Clear();
            foreach (var item in items)
            {
                Items.Add(item);
            }
            OnPropertyChanged(nameof(HasItems));
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Loading action items failed");
            ErrorMessage = "Couldn't load action items. Try again.";
        }
        finally
        {
            IsLoading = false;
        }
    }

    /// <summary>
    /// Apply a status filter and reload. Convenience for filter UI that sets the
    /// value and triggers the fetch in one call.
    /// </summary>
    public Task FilterByStatusAsync(ActionItemStatus? status, CancellationToken ct = default)
    {
        StatusFilter = status;
        return LoadAsync(ct);
    }

    /// <summary>Apply a priority filter and reload.</summary>
    public Task FilterByPriorityAsync(ActionItemPriority? priority, CancellationToken ct = default)
    {
        PriorityFilter = priority;
        return LoadAsync(ct);
    }

    /// <summary>
    /// Advance an item's status: anything not yet done becomes
    /// <see cref="ActionItemStatus.Completed"/>; a completed item flips back to
    /// <see cref="ActionItemStatus.Pending"/>. The server-returned item replaces the
    /// local one so state stays in sync.
    /// </summary>
    public async Task ToggleStatusAsync(ActionItem item, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(item);
        if (IsLoading)
        {
            return;
        }

        var nextStatus = item.Status == ActionItemStatus.Completed
            ? ActionItemStatus.Pending
            : ActionItemStatus.Completed;

        IsLoading = true;
        ErrorMessage = null;
        try
        {
            var updated = await _api
                .UpdateActionItemAsync(item.Id, new UpdateActionItemRequest(nextStatus, Priority: null), ct)
                .ConfigureAwait(false);
            ReplaceItem(item.Id, updated);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Updating action item status failed");
            ErrorMessage = "Couldn't update that task. Try again.";
        }
        finally
        {
            IsLoading = false;
        }
    }

    /// <summary>Delete an item; on success it is removed from <see cref="Items"/>.</summary>
    public async Task DeleteAsync(ActionItem item, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(item);
        if (IsLoading)
        {
            return;
        }

        IsLoading = true;
        ErrorMessage = null;
        try
        {
            await _api.DeleteActionItemAsync(item.Id, ct).ConfigureAwait(false);
            RemoveItem(item.Id);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Deleting action item failed");
            ErrorMessage = "Couldn't delete that task. Try again.";
        }
        finally
        {
            IsLoading = false;
        }
    }

    private void ReplaceItem(string id, ActionItem updated)
    {
        for (var i = 0; i < Items.Count; i++)
        {
            if (Items[i].Id == id)
            {
                Items[i] = updated;
                return;
            }
        }
        // The item is no longer in the visible list (e.g. it was filtered out before
        // the update returned). Surface it rather than silently dropping the result.
        Items.Add(updated);
        OnPropertyChanged(nameof(HasItems));
    }

    private void RemoveItem(string id)
    {
        for (var i = 0; i < Items.Count; i++)
        {
            if (Items[i].Id == id)
            {
                Items.RemoveAt(i);
                OnPropertyChanged(nameof(HasItems));
                return;
            }
        }
    }

    // The CommunityToolkit source generator calls this when IsLoading changes so the
    // command CanExecute guards (which all gate on !IsLoading) stay accurate.
    partial void OnIsLoadingChanged(bool value)
    {
        LoadCommand.NotifyCanExecuteChanged();
        ToggleStatusCommand.NotifyCanExecuteChanged();
        DeleteCommand.NotifyCanExecuteChanged();
    }
}
