using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.ViewModels;

/// <summary>Which backend search endpoint <see cref="SearchViewModel"/> queries.</summary>
public enum SearchMode
{
    /// <summary>Default blended ranking — <c>GET /api/search</c>.</summary>
    Hybrid,
    /// <summary>Embedding similarity with a score threshold — <c>GET /api/search/semantic</c>.</summary>
    Semantic,
    /// <summary>Postgres full-text search — <c>GET /api/search/fts</c>.</summary>
    FullText,
}

/// <summary>
/// Portable search ViewModel shared by the Windows (WinUI) and Linux (Avalonia)
/// search surfaces. Ports the macOS search behaviour: an observable
/// <see cref="Query"/>, a <see cref="Mode"/> selector that routes to one of the
/// three <see cref="IApiClient"/> search endpoints (hybrid / semantic / full-text),
/// and observable <see cref="Results"/> / <see cref="Total"/> / <see cref="IsSearching"/>
/// state. These are request/response calls (no background-thread events) so no
/// <c>IUiDispatcher</c> is needed. Failures surface on <see cref="ErrorMessage"/> —
/// no silent fallback, no fabricated empty result that masks a server error.
/// </summary>
public sealed partial class SearchViewModel : ObservableObject
{
    private readonly IApiClient _api;
    private readonly int _limit;
    private readonly double _semanticThreshold;
    private readonly ILogger<SearchViewModel> _logger;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SearchCommand))]
    private string _query = string.Empty;

    [ObservableProperty] private SearchMode _mode = SearchMode.Hybrid;
    [ObservableProperty] private int _total;
    [ObservableProperty] private bool _isSearching;
    [ObservableProperty] private string? _errorMessage;

    /// <summary>The current page of transcript-segment hits (empty until a search runs).</summary>
    public ObservableCollection<SearchHit> Results { get; } = new();

    public IAsyncRelayCommand SearchCommand { get; }
    public IRelayCommand ClearCommand { get; }

    public SearchViewModel(
        IApiClient api,
        int limit = 20,
        double semanticThreshold = 0.3,
        ILogger<SearchViewModel>? logger = null)
    {
        _api = api;
        _limit = limit;
        _semanticThreshold = semanticThreshold;
        _logger = logger ?? NullLogger<SearchViewModel>.Instance;

        SearchCommand = new AsyncRelayCommand(() => SearchAsync(CancellationToken.None), CanSearch);
        ClearCommand = new RelayCommand(Clear);
    }

    /// <summary>True once at least one search produced no hits (lets the UI show an empty state vs. an idle state).</summary>
    public bool HasNoResults => HasSearched && Results.Count == 0 && ErrorMessage is null;

    /// <summary>Whether a search has completed at least once this session.</summary>
    public bool HasSearched { get; private set; }

    private bool CanSearch() => !IsSearching && Query.Trim().Length > 0;

    /// <summary>Runs the query against the endpoint selected by <see cref="Mode"/>.</summary>
    public async Task SearchAsync(CancellationToken ct = default)
    {
        if (IsSearching)
        {
            return;
        }
        var query = Query.Trim();
        if (query.Length == 0)
        {
            // Empty query is a no-op, not an error: the command guard already blocks it.
            return;
        }

        IsSearching = true;
        ErrorMessage = null;
        try
        {
            var response = Mode switch
            {
                SearchMode.Semantic => await _api.SemanticSearchAsync(query, _limit, _semanticThreshold, ct).ConfigureAwait(false),
                SearchMode.FullText => await _api.FullTextSearchAsync(query, _limit, offset: 0, ct).ConfigureAwait(false),
                _ => await _api.SearchAsync(query, _limit, offset: 0, ct).ConfigureAwait(false),
            };

            Results.Clear();
            foreach (var hit in response.Results)
            {
                Results.Add(hit);
            }
            Total = response.Total;
            HasSearched = true;
            OnPropertyChanged(nameof(HasNoResults));
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            // Surface the failure; never swallow it into an empty result set.
            _logger.LogWarning(ex, "Search request failed");
            ErrorMessage = "Search failed. Please try again.";
            Results.Clear();
            Total = 0;
            OnPropertyChanged(nameof(HasNoResults));
        }
        finally
        {
            IsSearching = false;
        }
    }

    /// <summary>Resets the query, results, and any surfaced error back to the idle state.</summary>
    public void Clear()
    {
        Query = string.Empty;
        Results.Clear();
        Total = 0;
        ErrorMessage = null;
        HasSearched = false;
        OnPropertyChanged(nameof(HasNoResults));
    }

    // The CommunityToolkit source generator calls these when the backing properties change.
    partial void OnIsSearchingChanged(bool value) => SearchCommand.NotifyCanExecuteChanged();
}
