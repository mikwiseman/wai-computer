using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.ViewModels;

/// <summary>
/// Portable ViewModel for the extracted action-items surface, shared by the
/// Windows (WinUI) and Linux (Avalonia) clients. Binds the real
/// <see cref="IApiClient"/> action-item endpoints and the real <see cref="ActionItem"/>
/// shape (Task/Owner/Source, status pending|in_progress|completed|cancelled).
/// Request/response only — no background events. Failures surface on
/// <see cref="ErrorMessage"/>; nothing is silently swallowed.
/// </summary>
public sealed partial class ActionItemsViewModel : ObservableObject
{
    private readonly IApiClient _api;
    private readonly ILogger<ActionItemsViewModel> _logger;

    [ObservableProperty] private ActionItemStatus? _filterStatus;
    [ObservableProperty] private ActionItemPriority? _filterPriority;
    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private string? _errorMessage;

    public ObservableCollection<ActionItem> Items { get; } = new();

    public IAsyncRelayCommand RefreshCommand { get; }
    public IAsyncRelayCommand<ActionItem> ToggleStatusCommand { get; }
    public IAsyncRelayCommand<ActionItem> DeleteCommand { get; }

    public ActionItemsViewModel(IApiClient api, ILogger<ActionItemsViewModel>? logger = null)
    {
        _api = api;
        _logger = logger ?? NullLogger<ActionItemsViewModel>.Instance;
        RefreshCommand = new AsyncRelayCommand(() => LoadAsync(CancellationToken.None));
        ToggleStatusCommand = new AsyncRelayCommand<ActionItem>(item => ToggleStatusAsync(item, CancellationToken.None));
        DeleteCommand = new AsyncRelayCommand<ActionItem>(item => DeleteAsync(item, CancellationToken.None));
    }

    /// <summary>Loads action items honouring the current status/priority filters.</summary>
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
            var items = await _api.ListActionItemsAsync(FilterStatus, FilterPriority, ct).ConfigureAwait(false);
            Items.Clear();
            foreach (var item in items)
            {
                Items.Add(item);
            }
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

    /// <summary>Marks an item completed, or re-opens it (pending) if already completed.</summary>
    public async Task ToggleStatusAsync(ActionItem? item, CancellationToken ct = default)
    {
        if (item is null)
        {
            return;
        }
        var next = item.Status == ActionItemStatus.Completed ? ActionItemStatus.Pending : ActionItemStatus.Completed;
        try
        {
            var updated = await _api.UpdateActionItemAsync(item.Id, new UpdateActionItemRequest(next, null), ct).ConfigureAwait(false);
            var index = IndexOf(item.Id);
            if (index >= 0)
            {
                Items[index] = updated;
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Updating action item failed");
            ErrorMessage = "Couldn't update the action item. Try again.";
        }
    }

    public async Task DeleteAsync(ActionItem? item, CancellationToken ct = default)
    {
        if (item is null)
        {
            return;
        }
        try
        {
            await _api.DeleteActionItemAsync(item.Id, ct).ConfigureAwait(false);
            var index = IndexOf(item.Id);
            if (index >= 0)
            {
                Items.RemoveAt(index);
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Deleting action item failed");
            ErrorMessage = "Couldn't delete the action item. Try again.";
        }
    }

    private int IndexOf(string id)
    {
        for (var i = 0; i < Items.Count; i++)
        {
            if (Items[i].Id == id)
            {
                return i;
            }
        }
        return -1;
    }
}
