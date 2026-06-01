using System.Collections.Generic;
using FluentAssertions;
using WaiComputer.Core.Dictation;
using Xunit;

namespace WaiComputer.Core.Tests.Dictation;

public class DictationLanguageStoreTests
{
    private sealed class FakePreferences : IPreferences
    {
        private readonly Dictionary<string, string> _values = new();
        public FakePreferences(params (string key, string value)[] seed)
        {
            foreach (var (k, v) in seed) _values[k] = v;
        }
        public string? Get(string key) => _values.TryGetValue(key, out var v) ? v : null;
        public void Set(string key, string value) => _values[key] = value;
    }

    [Fact]
    public void DefaultsToAutoDetect()
    {
        var store = new DictationLanguageStore(new FakePreferences());
        store.IsAutoDetect.Should().BeTrue();
        store.WireLanguageTag.Should().Be("");
    }

    [Fact]
    public void MigratesLegacySingleLanguage()
    {
        var store = new DictationLanguageStore(new FakePreferences((DictationLanguageStore.LegacyKey, "ru")));
        store.IsAutoDetect.Should().BeFalse();
        store.WireLanguageTag.Should().Be("ru");
        store.SelectedLanguages.Should().BeEquivalentTo(new[] { "ru" });
    }

    [Fact]
    public void MigratesLegacyMultiToAutoDetect()
    {
        var store = new DictationLanguageStore(new FakePreferences((DictationLanguageStore.LegacyKey, "multi")));
        store.IsAutoDetect.Should().BeTrue();
    }

    [Fact]
    public void LoadsFromJsonArray()
    {
        var store = new DictationLanguageStore(new FakePreferences((DictationLanguageStore.PreferencesKey, "[\"ru\"]")));
        store.WireLanguageTag.Should().Be("ru");
    }

    [Fact]
    public void SetSingleLanguagePersistsAndMirrorsLegacy()
    {
        var prefs = new FakePreferences();
        var store = new DictationLanguageStore(prefs);
        store.SetLanguages(new[] { "RU " }); // normalized: trim + lowercase
        store.WireLanguageTag.Should().Be("ru");
        prefs.Get(DictationLanguageStore.LegacyKey).Should().Be("ru");
    }

    [Fact]
    public void TogglingTheSelectedLanguageClearsToAutoDetect()
    {
        var store = new DictationLanguageStore(new FakePreferences());
        store.Toggle("ru");
        store.WireLanguageTag.Should().Be("ru");
        store.Toggle("ru");
        store.IsAutoDetect.Should().BeTrue();
    }

    [Theory]
    [InlineData(null, "multi")]
    [InlineData("", "multi")]
    [InlineData("multi", "multi")]
    [InlineData("auto", "multi")]
    [InlineData("ru", "ru")]
    public void ProviderLanguagePolicyMapsWireTag(string? wireTag, string expected)
        => DictationLanguageSelectionPolicy.ProviderLanguage(wireTag).Should().Be(expected);

    [Theory]
    [InlineData(null, null, "deepgram", "nova-3", false)]   // no previous -> keep
    [InlineData("deepgram", "nova-3", "deepgram", "nova-3", false)] // unchanged
    [InlineData("deepgram", "nova-3", "openai", "nova-3", true)]    // provider changed
    [InlineData("deepgram", "nova-3", "deepgram", "nova-2", true)]  // model changed
    public void VaultInvalidationMatchesMac(string? pp, string? pm, string np, string nm, bool expected)
        => DictationSessionConfigInvalidationPolicy.ShouldClearVault(pp, pm, np, nm).Should().Be(expected);

    [Fact]
    public void CatalogHasExpectedEntries()
    {
        DictationLanguageCatalog.All.Should().HaveCount(15);
        DictationLanguageCatalog.Entry("ru")!.NativeName.Should().Be("Русский");
        DictationLanguageCatalog.Entry("xx").Should().BeNull();
    }
}
