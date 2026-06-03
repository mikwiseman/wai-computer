using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Time;

namespace WaiComputer.Core.Dictation;

/// <summary>Identity of a realtime session config (porting the macOS vault Key).</summary>
public readonly record struct VaultKey(string Language, int Channels, string Purpose);

/// <summary>A consumed session config plus how it was sourced.</summary>
public sealed record VaultTakeResult(RealtimeTranscriptionSessionConfig Config, bool Prefetched, int TokenAgeMilliseconds);

/// <summary>Mints a fresh realtime session config for a key (typically <c>IApiClient.CreateRealtimeTranscriptionSessionAsync</c>).</summary>
public delegate Task<RealtimeTranscriptionSessionConfig> RealtimeConfigMinter(VaultKey key, CancellationToken ct);

/// <summary>Raised when a minted/cached config doesn't match what the caller expected (no silent mismatch).</summary>
public sealed class DictationSessionConfigVaultException : Exception
{
    public DictationSessionConfigVaultException(string message) : base(message) { }

    public static DictationSessionConfigVaultException UnexpectedLanguage(string expected, string actual)
        => new($"Realtime session config language mismatch: expected '{expected}', got '{actual}'.");

    public static DictationSessionConfigVaultException UnexpectedProvider(string? expectedProvider, string? expectedModel, string actualProvider, string actualModel)
        => new($"Realtime session config provider/model mismatch: expected '{expectedProvider}/{expectedModel}', got '{actualProvider}/{actualModel}'.");
}

/// <summary>
/// Caches a single short-lived realtime transcription session config so dictation
/// can connect instantly. The cached value carries provider endpoint metadata + a
/// temporary credential; it does NOT open the mic or a provider socket. Values are
/// consumed on use because some providers treat realtime credentials as
/// single-session. Ports the macOS <c>RealtimeTranscriptionSessionConfigVault</c>.
///
/// <see cref="Prefetch"/> mints in the background (e.g. on hotkey key-down);
/// <see cref="TakeAsync"/> returns the warm config if it is still alive and matches
/// the expected language/provider/model, otherwise it awaits an in-flight prefetch
/// for the same key, otherwise it mints fresh. A mismatch throws rather than
/// returning a stale config (no fallback).
/// </summary>
public sealed class DictationSessionConfigVault
{
    private sealed record Entry(VaultKey Key, RealtimeTranscriptionSessionConfig Config, DateTimeOffset MintedAt);

    private sealed class InFlight
    {
        public required Guid Id { get; init; }
        public required VaultKey Key { get; init; }
        public required Task<Entry> Task { get; init; }
        public required CancellationTokenSource Cts { get; init; }
    }

    private readonly RealtimeConfigMinter _minter;
    private readonly ISystemClock _clock;
    private readonly object _lock = new();
    private Entry? _cached;
    private InFlight? _inFlight;

    public DictationSessionConfigVault(RealtimeConfigMinter minter, ISystemClock clock)
    {
        _minter = minter;
        _clock = clock;
    }

    /// <summary>Warm the cache for <paramref name="key"/> in the background. No-op if a live entry or matching mint is already pending.</summary>
    public void Prefetch(VaultKey key)
    {
        lock (_lock)
        {
            var now = _clock.UtcNow;
            if (_cached is { } cached && cached.Key == key && IsAlive(cached, now))
            {
                return;
            }
            if (_inFlight is { } inFlight && inFlight.Key == key)
            {
                return;
            }
            StartInFlightLocked(key);
        }
    }

    /// <summary>
    /// Take a config for <paramref name="key"/>: the warm prefetch if alive + matching,
    /// else an in-flight prefetch for the same key, else a fresh mint. Throws if the
    /// resulting config's language/provider/model don't match the expectation.
    /// </summary>
    public async Task<VaultTakeResult> TakeAsync(
        VaultKey key,
        string? expectedProvider = null,
        string? expectedModel = null,
        CancellationToken ct = default)
    {
        Task<Entry>? pending = null;
        lock (_lock)
        {
            var now = _clock.UtcNow;
            if (_cached is { } cached
                && cached.Key == key
                && IsAlive(cached, now)
                && Matches(cached.Config, key.Language, expectedProvider, expectedModel))
            {
                _cached = null;
                return Validate(cached, prefetched: true, key.Language, expectedProvider, expectedModel);
            }

            _cached = null; // stale / mismatched — drop it

            if (_inFlight is { } inFlight && inFlight.Key == key)
            {
                pending = inFlight.Task;
                _inFlight = null; // hand the prefetch over to this take
            }
        }

        if (pending is not null)
        {
            var prefetchedEntry = await pending.ConfigureAwait(false);
            return Validate(prefetchedEntry, prefetched: true, key.Language, expectedProvider, expectedModel);
        }

        var fresh = await MintEntryAsync(key, ct).ConfigureAwait(false);
        return Validate(fresh, prefetched: false, key.Language, expectedProvider, expectedModel);
    }

    /// <summary>Drop the cache + cancel any in-flight prefetch (e.g. after a provider/model change).</summary>
    public void Clear()
    {
        InFlight? inFlight;
        lock (_lock)
        {
            _cached = null;
            inFlight = _inFlight;
            _inFlight = null;
        }
        inFlight?.Cts.Cancel();
        inFlight?.Cts.Dispose();
    }

    private void StartInFlightLocked(VaultKey key)
    {
        var id = Guid.NewGuid();
        var cts = new CancellationTokenSource();
        var task = MintEntryAsync(key, cts.Token);
        _inFlight = new InFlight { Id = id, Key = key, Task = task, Cts = cts };
        _ = ObservePrefetchAsync(id, task, cts);
    }

    private async Task ObservePrefetchAsync(Guid id, Task<Entry> task, CancellationTokenSource cts)
    {
        try
        {
            var entry = await task.ConfigureAwait(false);
            lock (_lock)
            {
                if (_inFlight is { } active && active.Id == id)
                {
                    _cached = entry;
                    _inFlight = null;
                }
            }
        }
        catch
        {
            lock (_lock)
            {
                if (_inFlight is { } active && active.Id == id)
                {
                    _inFlight = null;
                }
            }
        }
        finally
        {
            cts.Dispose();
        }
    }

    private async Task<Entry> MintEntryAsync(VaultKey key, CancellationToken ct)
    {
        var config = await _minter(key, ct).ConfigureAwait(false);
        return new Entry(key, config, _clock.UtcNow);
    }

    private VaultTakeResult Validate(Entry entry, bool prefetched, string expectedLanguage, string? expectedProvider, string? expectedModel)
    {
        if (!LanguageMatches(entry.Config.Language, expectedLanguage))
        {
            throw DictationSessionConfigVaultException.UnexpectedLanguage(expectedLanguage, entry.Config.Language);
        }
        if (!Matches(entry.Config, expectedLanguage, expectedProvider, expectedModel))
        {
            throw DictationSessionConfigVaultException.UnexpectedProvider(
                expectedProvider, expectedModel, ProviderWire(entry.Config.Provider), entry.Config.Model);
        }

        var ageMs = prefetched ? (int)Math.Max(0, (_clock.UtcNow - entry.MintedAt).TotalMilliseconds) : 0;
        return new VaultTakeResult(entry.Config, prefetched, ageMs);
    }

    private bool IsAlive(Entry entry, DateTimeOffset now)
    {
        var lifetime = Math.Max(entry.Config.ExpiresInSeconds, 0);
        if (lifetime <= 0)
        {
            return false;
        }
        var safety = Math.Min(30, Math.Max(3, lifetime / 4));
        return entry.MintedAt.AddSeconds(lifetime - safety) > now;
    }

    private static bool Matches(RealtimeTranscriptionSessionConfig config, string expectedLanguage, string? expectedProvider, string? expectedModel)
    {
        if (!LanguageMatches(config.Language, expectedLanguage))
        {
            return false;
        }
        if (expectedProvider is not null && !string.Equals(ProviderWire(config.Provider), expectedProvider, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }
        if (expectedModel is not null && config.Model != expectedModel)
        {
            return false;
        }
        return true;
    }

    private static bool LanguageMatches(string actual, string expected)
    {
        var a = NormalizedLanguage(actual);
        var e = NormalizedLanguage(expected);
        return a == e || e.StartsWith($"{a}-", StringComparison.Ordinal);
    }

    private static string NormalizedLanguage(string language)
    {
        var normalized = language.Trim().ToLowerInvariant().Replace('_', '-');
        return normalized is "" or "auto" or "und" ? "multi" : normalized;
    }

    private static string ProviderWire(RealtimeProvider provider) => provider switch
    {
        RealtimeProvider.Deepgram => "deepgram",
        _ => provider.ToString().ToLowerInvariant(),
    };
}
