using System.Linq;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Time;

namespace WaiComputer.Core.Dictation;

/// <summary>One completed dictation. Ports the macOS <c>DictationHistoryEntry</c>.</summary>
public sealed record DictationHistoryEntry(
    Guid Id,
    DateTimeOffset Timestamp,
    string RawText,
    string? CleanedText,
    double DurationSeconds,
    int WordCount)
{
    public string DisplayText => CleanedText ?? RawText;

    /// <summary>Word count of (cleaned ?? raw), collapsing runs of whitespace (matches Mac split).</summary>
    public static int CountWords(string text) => text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries).Length;
}

/// <summary>
/// Local-first dictation history cached via <see cref="IDictationLocalStore"/>
/// (survives logout) + best-effort backend sync (tombstoned deletes, hydrate
/// merge). Ports the macOS <c>DictationHistoryStore</c>, including the stats
/// (total words, average WPM, day streak). Remote failures are logged + retried
/// on hydrate — the local cache is the session source of truth.
/// </summary>
public sealed class DictationHistoryStore
{
    private const string EntriesKey = "dictation_history";
    private const string TombstonesKey = "dictation_history_tombstones";

    private readonly IDictationLocalStore _local;
    private readonly IApiClient _api;
    private readonly ISystemClock _clock;
    private readonly ILogger<DictationHistoryStore> _logger;
    private readonly object _gate = new();
    private List<DictationHistoryEntry> _entries = new();
    private HashSet<Guid> _tombstones = new();

    public DictationHistoryStore(IDictationLocalStore local, IApiClient api, ISystemClock clock, ILogger<DictationHistoryStore>? logger = null)
    {
        _local = local;
        _api = api;
        _clock = clock;
        _logger = logger ?? NullLogger<DictationHistoryStore>.Instance;
    }

    public IReadOnlyList<DictationHistoryEntry> Entries
    {
        get { lock (_gate) { return _entries.ToList(); } }
    }

    public int TotalWords
    {
        get { lock (_gate) { return _entries.Sum(e => e.WordCount); } }
    }

    public int AverageWpm
    {
        get
        {
            lock (_gate)
            {
                var totalDuration = _entries.Sum(e => e.DurationSeconds);
                if (totalDuration <= 0) return 0;
                return (int)(_entries.Sum(e => e.WordCount) / (totalDuration / 60.0));
            }
        }
    }

    /// <summary>Consecutive days (UTC) ending today/yesterday with at least one dictation.</summary>
    public int StreakDays
    {
        get
        {
            HashSet<DateOnly> days;
            DateOnly today;
            lock (_gate)
            {
                if (_entries.Count == 0) return 0;
                days = _entries.Select(e => DateOnly.FromDateTime(e.Timestamp.UtcDateTime)).ToHashSet();
                today = DateOnly.FromDateTime(_clock.UtcNow.UtcDateTime);
            }

            var current = today;
            if (!days.Contains(current))
            {
                current = current.AddDays(-1);
                if (!days.Contains(current)) return 0; // nothing today or yesterday
            }

            var streak = 1;
            while (days.Contains(current.AddDays(-1)))
            {
                streak++;
                current = current.AddDays(-1);
            }
            return streak;
        }
    }

    public async Task LoadAsync(CancellationToken ct)
    {
        var entries = await _local.ReadAsync<List<DictationHistoryEntry>>(EntriesKey, ct).ConfigureAwait(false) ?? new List<DictationHistoryEntry>();
        var tombs = await _local.ReadAsync<List<Guid>>(TombstonesKey, ct).ConfigureAwait(false) ?? new List<Guid>();
        lock (_gate) { _entries = entries; _tombstones = new HashSet<Guid>(tombs); }
    }

    public async Task AddAsync(string rawText, string? cleanedText, double durationSeconds, CancellationToken ct)
    {
        var entry = new DictationHistoryEntry(
            Guid.NewGuid(),
            _clock.UtcNow,
            rawText,
            cleanedText,
            durationSeconds,
            DictationHistoryEntry.CountWords(cleanedText ?? rawText));
        lock (_gate) { _entries.Insert(0, entry); }
        await SaveEntriesAsync(ct).ConfigureAwait(false);
        await PushEntryAsync(entry, ct).ConfigureAwait(false);
    }

    public async Task DeleteAsync(Guid id, CancellationToken ct)
    {
        lock (_gate) { _entries.RemoveAll(e => e.Id == id); _tombstones.Add(id); }
        await SaveEntriesAsync(ct).ConfigureAwait(false);
        await SaveTombstonesAsync(ct).ConfigureAwait(false);
        try
        {
            await _api.DeleteDictationEntryAsync(id, ct).ConfigureAwait(false);
            lock (_gate) { _tombstones.Remove(id); }
            await SaveTombstonesAsync(ct).ConfigureAwait(false);
        }
        catch (Exception ex) { _logger.LogWarning(ex, "Delete dictation entry failed; tombstone retained"); }
    }

    public async Task ClearLocalCacheAsync(CancellationToken ct)
    {
        lock (_gate) { _entries.Clear(); _tombstones.Clear(); }
        await SaveEntriesAsync(ct).ConfigureAwait(false);
        await SaveTombstonesAsync(ct).ConfigureAwait(false);
    }

    /// <summary>Pull server entries, replay tombstoned deletes, merge server-only, push local-only.</summary>
    public async Task HydrateAsync(CancellationToken ct)
    {
        IReadOnlyList<DictationEntryDto> server;
        try { server = await _api.ListDictationEntriesAsync(ct).ConfigureAwait(false); }
        catch (Exception ex) { _logger.LogWarning(ex, "Hydrate history fetch failed"); return; }

        HashSet<Guid> tombs;
        HashSet<Guid> localIds;
        lock (_gate) { tombs = new HashSet<Guid>(_tombstones); localIds = _entries.Select(e => e.Id).ToHashSet(); }

        foreach (var s in server.Where(s => tombs.Contains(s.ClientEntryId)))
        {
            try { await _api.DeleteDictationEntryAsync(s.ClientEntryId, ct).ConfigureAwait(false); lock (_gate) { _tombstones.Remove(s.ClientEntryId); } }
            catch (Exception ex) { _logger.LogWarning(ex, "Hydrate tombstone replay failed"); }
        }
        await SaveTombstonesAsync(ct).ConfigureAwait(false);

        var additions = server
            .Where(s => !localIds.Contains(s.ClientEntryId) && !tombs.Contains(s.ClientEntryId))
            .Select(s => new DictationHistoryEntry(s.ClientEntryId, s.OccurredAt, s.RawText, s.CleanedText, s.DurationSeconds, s.WordCount))
            .ToList();
        if (additions.Count > 0)
        {
            lock (_gate)
            {
                _entries.AddRange(additions);
                _entries = _entries.OrderByDescending(e => e.Timestamp).ToList();
            }
            await SaveEntriesAsync(ct).ConfigureAwait(false);
        }

        var serverIds = server.Select(s => s.ClientEntryId).ToHashSet();
        List<DictationHistoryEntry> localOnly;
        lock (_gate) { localOnly = _entries.Where(e => !serverIds.Contains(e.Id)).ToList(); }
        foreach (var entry in localOnly)
        {
            await PushEntryAsync(entry, ct).ConfigureAwait(false);
        }
    }

    private async Task PushEntryAsync(DictationHistoryEntry entry, CancellationToken ct)
    {
        try
        {
            await _api.CreateDictationEntryAsync(
                new CreateDictationEntryRequest(entry.Id, entry.RawText, entry.CleanedText, entry.DurationSeconds, entry.WordCount, entry.Timestamp), ct).ConfigureAwait(false);
        }
        catch (Exception ex) { _logger.LogWarning(ex, "Push dictation entry failed; will retry on next hydrate"); }
    }

    private Task SaveEntriesAsync(CancellationToken ct)
    {
        List<DictationHistoryEntry> snapshot;
        lock (_gate) { snapshot = _entries.ToList(); }
        return _local.WriteAsync(EntriesKey, snapshot, ct);
    }

    private Task SaveTombstonesAsync(CancellationToken ct)
    {
        List<Guid> snapshot;
        lock (_gate) { snapshot = _tombstones.ToList(); }
        return _local.WriteAsync(TombstonesKey, snapshot, ct);
    }
}
