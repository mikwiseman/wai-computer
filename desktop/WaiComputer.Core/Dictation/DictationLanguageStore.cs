using System.Linq;
using System.Text.Json;

namespace WaiComputer.Core.Dictation;

/// <summary>Key-value preferences port (Windows registry / Linux config file). Platforms implement.</summary>
public interface IPreferences
{
    string? Get(string key);
    void Set(string key, string value);
}

/// <summary>
/// Source of truth for the user's dictation language preference, porting the
/// macOS <c>DictationLanguageStore</c>. Stored as a JSON array of BCP-47 codes:
/// 0 entries = multilingual auto-detect (wire tag <c>""</c>); 1 entry =
/// single-language mode (that code). Migrates the legacy single
/// <c>transcriptionLanguage</c> string on first read and mirrors back to it.
/// </summary>
public sealed class DictationLanguageStore
{
    public const string PreferencesKey = "dictationLanguages";
    public const string LegacyKey = "transcriptionLanguage";

    private readonly IPreferences _prefs;
    private HashSet<string> _selected;

    public DictationLanguageStore(IPreferences prefs)
    {
        _prefs = prefs;
        _selected = LoadOrMigrate(prefs);
        Persist(_selected);
    }

    public IReadOnlySet<string> SelectedLanguages => _selected;

    /// <summary>Empty when the user lets the model auto-detect across all languages.</summary>
    public bool IsAutoDetect => _selected.Count == 0;

    /// <summary>What we send upstream: the single code, or <c>""</c> for auto-detect.</summary>
    public string WireLanguageTag => _selected.Count == 1 ? _selected.First() : string.Empty;

    public void SetLanguages(IEnumerable<string> languages)
    {
        _selected = NormalizedSelection(languages);
        Persist(_selected);
    }

    public void Toggle(string language)
    {
        var normalized = NormalizedLanguage(language);
        if (normalized is null)
        {
            return;
        }
        if (_selected.Count == 1 && _selected.Contains(normalized))
        {
            SetAutoDetect();
        }
        else
        {
            SetLanguages(new[] { normalized });
        }
    }

    public void SetAutoDetect() => SetLanguages(Array.Empty<string>());

    private void Persist(HashSet<string> languages)
    {
        var sorted = languages.OrderBy(x => x, StringComparer.Ordinal).ToArray();
        _prefs.Set(PreferencesKey, JsonSerializer.Serialize(sorted));
        // Mirror to the legacy single-string key so older code paths keep working.
        _prefs.Set(LegacyKey, languages.Count == 1 ? languages.First() : "multi");
    }

    private static HashSet<string> LoadOrMigrate(IPreferences prefs)
    {
        var raw = prefs.Get(PreferencesKey);
        if (raw is not null)
        {
            try
            {
                var array = JsonSerializer.Deserialize<string[]>(raw);
                if (array is not null)
                {
                    return NormalizedSelection(array);
                }
            }
            catch (JsonException) { /* fall through to legacy / default */ }
        }

        var legacy = prefs.Get(LegacyKey);
        if (legacy is not null)
        {
            return legacy is "multi" or "" ? new HashSet<string>() : NormalizedSelection(new[] { legacy });
        }

        return new HashSet<string>(); // default: auto-detect
    }

    private static HashSet<string> NormalizedSelection(IEnumerable<string> languages)
    {
        var cleaned = new HashSet<string>(languages.Select(NormalizedLanguage).OfType<string>(), StringComparer.Ordinal);
        return cleaned.Count == 1 ? cleaned : new HashSet<string>();
    }

    private static string? NormalizedLanguage(string language)
    {
        var normalized = language.Trim().ToLowerInvariant();
        return normalized is "" or "multi" or "auto" ? null : normalized;
    }
}

/// <summary>Maps the stored wire tag onto the provider's language parameter (auto-detect = "multi").</summary>
public static class DictationLanguageSelectionPolicy
{
    public static string ProviderLanguage(string? wireTag)
    {
        var normalized = wireTag?.Trim().ToLowerInvariant();
        return string.IsNullOrEmpty(normalized) || normalized is "multi" or "auto" ? "multi" : normalized;
    }
}

/// <summary>Whether a cached realtime session config must be discarded after a provider/model change.</summary>
public static class DictationSessionConfigInvalidationPolicy
{
    public static bool ShouldClearVault(string? previousProvider, string? previousModel, string nextProvider, string nextModel)
    {
        if (previousProvider is null || previousModel is null)
        {
            return false;
        }
        return previousProvider != nextProvider || previousModel != nextModel;
    }
}

/// <summary>A selectable dictation language (picker UI).</summary>
public sealed record DictationLanguage(string Code, string EnglishName, string NativeName);

/// <summary>Static catalogue of picker languages, ordered by WaiComputer usage frequency.</summary>
public static class DictationLanguageCatalog
{
    public static IReadOnlyList<DictationLanguage> All { get; } = new[]
    {
        new DictationLanguage("en", "English", "English"),
        new DictationLanguage("ru", "Russian", "Русский"),
        new DictationLanguage("es", "Spanish", "Español"),
        new DictationLanguage("de", "German", "Deutsch"),
        new DictationLanguage("fr", "French", "Français"),
        new DictationLanguage("it", "Italian", "Italiano"),
        new DictationLanguage("pt", "Portuguese", "Português"),
        new DictationLanguage("ja", "Japanese", "日本語"),
        new DictationLanguage("ko", "Korean", "한국어"),
        new DictationLanguage("hi", "Hindi", "हिन्दी"),
        new DictationLanguage("ar", "Arabic", "العربية"),
        new DictationLanguage("uk", "Ukrainian", "Українська"),
        new DictationLanguage("pl", "Polish", "Polski"),
        new DictationLanguage("nl", "Dutch", "Nederlands"),
        new DictationLanguage("tr", "Turkish", "Türkçe"),
    };

    public static DictationLanguage? Entry(string code) => All.FirstOrDefault(e => e.Code == code);
}
