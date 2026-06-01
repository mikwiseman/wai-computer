using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Dictation;
using WaiComputer.Core.Time;
using WireMock.Server;
using Xunit;

namespace WaiComputer.Core.Tests.Dictation;

public class DictationDictionaryStoreTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;
    private FakeLocalStore _local = null!;
    private DictationDictionaryStore _store = null!;

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        _local = new FakeLocalStore();
        _store = new DictationDictionaryStore(_local, _client, new FixedClock());
        return Task.CompletedTask;
    }

    public Task DisposeAsync()
    {
        _client.Dispose();
        _server.Stop();
        _server.Dispose();
        return Task.CompletedTask;
    }

    private static DictionaryWord W(string word, string? replacement)
        => new(Guid.NewGuid(), word, replacement, new DateTimeOffset(2026, 6, 1, 12, 0, 0, TimeSpan.Zero));

    [Fact]
    public async Task ApplyReplacementsIsCaseInsensitiveAndSkipsBoosters()
    {
        _local.Seed("dictation_dictionary", new List<DictionaryWord>
        {
            W("WaiComputer", "Wai Computer"),
            W("teh", "the"),
            W("boost", null), // a booster — no replacement, must not be substituted
        });
        await _store.LoadAsync(CancellationToken.None);

        _store.ApplyReplacements("i use waicomputer and teh boost")
            .Should().Be("i use Wai Computer and the boost");
    }

    [Fact]
    public async Task VocabularyListReturnsAllWords()
    {
        _local.Seed("dictation_dictionary", new List<DictionaryWord> { W("WaiComputer", null), W("Deepgram", null) });
        await _store.LoadAsync(CancellationToken.None);

        _store.VocabularyList.Should().BeEquivalentTo(new[] { "WaiComputer", "Deepgram" });
    }

    [Fact]
    public async Task AddDedupsByWordCaseInsensitive()
    {
        await _store.AddAsync("Hello", null, CancellationToken.None);
        await _store.AddAsync("hello", null, CancellationToken.None); // duplicate (case-insensitive)

        _store.VocabularyList.Should().ContainSingle().Which.Should().Be("Hello");
    }

    [Fact]
    public async Task AddSkipsEmpty()
    {
        await _store.AddAsync("   ", null, CancellationToken.None);
        _store.Words.Should().BeEmpty();
    }

    private sealed class FakeLocalStore : IDictationLocalStore
    {
        private readonly Dictionary<string, object?> _values = new();
        public void Seed<T>(string key, T value) => _values[key] = value;
        public Task<T?> ReadAsync<T>(string key, CancellationToken ct)
            => Task.FromResult(_values.TryGetValue(key, out var v) && v is T t ? t : default);
        public Task WriteAsync<T>(string key, T value, CancellationToken ct)
        {
            _values[key] = value;
            return Task.CompletedTask;
        }
    }

    private sealed class FixedClock : ISystemClock
    {
        public DateTimeOffset UtcNow => new(2026, 6, 1, 12, 0, 0, TimeSpan.Zero);
        public Task Delay(TimeSpan duration, CancellationToken ct) => Task.CompletedTask;
    }
}
