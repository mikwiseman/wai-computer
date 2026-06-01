using System.Linq;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Time;

namespace WaiComputer.Core.Dictation;

/// <summary>
/// A personal-dictionary entry. With no replacement it is a vocabulary booster
/// (improves recognition); with a replacement it is an auto-correction applied
/// after transcription. Ports the macOS <c>DictionaryWord</c>.
/// </summary>
public sealed record DictionaryWord(Guid Id, string Word, string? Replacement, DateTimeOffset CreatedAt)
{
    public bool IsReplacement => Replacement is not null && Replacement != Word;
}

/// <summary>
/// Local-first dictation dictionary: vocabulary hints for the provider +
/// post-transcription replacements. Cached via <see cref="IDictationLocalStore"/>
/// (survives logout) and best-effort synced to the backend. Ports the macOS
/// <c>DictationDictionaryStore</c>. Remote failures are logged and retried on the
/// next <see cref="HydrateAsync"/> — the local cache is the session source of truth.
/// </summary>
public sealed class DictationDictionaryStore
{
    private const string WordsKey = "dictation_dictionary";
    private const string TombstonesKey = "dictation_dictionary_tombstones";

    private readonly IDictationLocalStore _local;
    private readonly IApiClient _api;
    private readonly ISystemClock _clock;
    private readonly ILogger<DictationDictionaryStore> _logger;
    private readonly object _gate = new();
    private List<DictionaryWord> _words = new();
    private HashSet<Guid> _tombstones = new();

    public DictationDictionaryStore(IDictationLocalStore local, IApiClient api, ISystemClock clock, ILogger<DictationDictionaryStore>? logger = null)
    {
        _local = local;
        _api = api;
        _clock = clock;
        _logger = logger ?? NullLogger<DictationDictionaryStore>.Instance;
    }

    public IReadOnlyList<DictionaryWord> Words
    {
        get { lock (_gate) { return _words.ToList(); } }
    }

    /// <summary>Vocabulary list sent to the transcription provider for prompt conditioning.</summary>
    public IReadOnlyList<string> VocabularyList
    {
        get { lock (_gate) { return _words.Select(w => w.Word).ToList(); } }
    }

    public async Task LoadAsync(CancellationToken ct)
    {
        var words = await _local.ReadAsync<List<DictionaryWord>>(WordsKey, ct).ConfigureAwait(false) ?? new List<DictionaryWord>();
        var tombs = await _local.ReadAsync<List<Guid>>(TombstonesKey, ct).ConfigureAwait(false) ?? new List<Guid>();
        lock (_gate) { _words = words; _tombstones = new HashSet<Guid>(tombs); }
    }

    /// <summary>Apply case-insensitive replacement rules to transcribed text (vocabulary boosters are not substituted).</summary>
    public string ApplyReplacements(string text)
    {
        List<DictionaryWord> words;
        lock (_gate) { words = _words.Where(w => w.IsReplacement).ToList(); }
        var result = text;
        foreach (var word in words)
        {
            result = result.Replace(word.Word, word.Replacement!, StringComparison.OrdinalIgnoreCase);
        }
        return result;
    }

    public async Task AddAsync(string word, string? replacement, CancellationToken ct)
    {
        var trimmed = word.Trim();
        if (trimmed.Length == 0)
        {
            return;
        }

        DictionaryWord entry;
        lock (_gate)
        {
            if (_words.Any(w => string.Equals(w.Word, trimmed, StringComparison.OrdinalIgnoreCase)))
            {
                return; // dedup by word (case-insensitive)
            }
            entry = new DictionaryWord(Guid.NewGuid(), trimmed, replacement, _clock.UtcNow);
            _words.Add(entry);
            _words.Sort((a, b) => string.Compare(a.Word, b.Word, StringComparison.OrdinalIgnoreCase));
        }

        await SaveWordsAsync(ct).ConfigureAwait(false);
        await PushWordAsync(entry, ct).ConfigureAwait(false);
    }

    public async Task DeleteAsync(Guid id, CancellationToken ct)
    {
        lock (_gate)
        {
            _words.RemoveAll(w => w.Id == id);
            _tombstones.Add(id);
        }
        await SaveWordsAsync(ct).ConfigureAwait(false);
        await SaveTombstonesAsync(ct).ConfigureAwait(false);
        try
        {
            await _api.DeleteDictionaryWordAsync(id, ct).ConfigureAwait(false);
            lock (_gate) { _tombstones.Remove(id); }
            await SaveTombstonesAsync(ct).ConfigureAwait(false);
        }
        catch (Exception ex) { _logger.LogWarning(ex, "Delete dictionary word failed; tombstone retained"); }
    }

    /// <summary>Pull server state, replay tombstoned deletes, merge server-only words, push local-only words.</summary>
    public async Task HydrateAsync(CancellationToken ct)
    {
        IReadOnlyList<DictionaryWordDto> server;
        try { server = await _api.ListDictionaryAsync(ct).ConfigureAwait(false); }
        catch (Exception ex) { _logger.LogWarning(ex, "Hydrate dictionary fetch failed"); return; }

        HashSet<Guid> tombs;
        HashSet<Guid> localIds;
        lock (_gate) { tombs = new HashSet<Guid>(_tombstones); localIds = _words.Select(w => w.Id).ToHashSet(); }

        foreach (var s in server.Where(s => tombs.Contains(s.ClientWordId)))
        {
            try { await _api.DeleteDictionaryWordAsync(s.ClientWordId, ct).ConfigureAwait(false); lock (_gate) { _tombstones.Remove(s.ClientWordId); } }
            catch (Exception ex) { _logger.LogWarning(ex, "Hydrate tombstone replay failed"); }
        }
        await SaveTombstonesAsync(ct).ConfigureAwait(false);

        var additions = server
            .Where(s => !localIds.Contains(s.ClientWordId) && !tombs.Contains(s.ClientWordId))
            .Select(s => new DictionaryWord(s.ClientWordId, s.Word, s.Replacement, s.OccurredAt))
            .ToList();
        if (additions.Count > 0)
        {
            lock (_gate)
            {
                _words.AddRange(additions);
                _words.Sort((a, b) => string.Compare(a.Word, b.Word, StringComparison.OrdinalIgnoreCase));
            }
            await SaveWordsAsync(ct).ConfigureAwait(false);
        }

        var serverIds = server.Select(s => s.ClientWordId).ToHashSet();
        List<DictionaryWord> localOnly;
        lock (_gate) { localOnly = _words.Where(w => !serverIds.Contains(w.Id)).ToList(); }
        foreach (var entry in localOnly)
        {
            await PushWordAsync(entry, ct).ConfigureAwait(false);
        }
    }

    public async Task ClearLocalCacheAsync(CancellationToken ct)
    {
        lock (_gate) { _words.Clear(); _tombstones.Clear(); }
        await SaveWordsAsync(ct).ConfigureAwait(false);
        await SaveTombstonesAsync(ct).ConfigureAwait(false);
    }

    private async Task PushWordAsync(DictionaryWord entry, CancellationToken ct)
    {
        try { await _api.CreateDictionaryWordAsync(new CreateDictionaryWordRequest(entry.Id, entry.Word, entry.Replacement, entry.CreatedAt), ct).ConfigureAwait(false); }
        catch (Exception ex) { _logger.LogWarning(ex, "Push dictionary word failed; will retry on next hydrate"); }
    }

    private Task SaveWordsAsync(CancellationToken ct)
    {
        List<DictionaryWord> snapshot;
        lock (_gate) { snapshot = _words.ToList(); }
        return _local.WriteAsync(WordsKey, snapshot, ct);
    }

    private Task SaveTombstonesAsync(CancellationToken ct)
    {
        List<Guid> snapshot;
        lock (_gate) { snapshot = _tombstones.ToList(); }
        return _local.WriteAsync(TombstonesKey, snapshot, ct);
    }
}
