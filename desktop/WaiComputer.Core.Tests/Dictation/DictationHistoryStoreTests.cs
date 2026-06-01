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

public class DictationHistoryStoreTests : IAsyncLifetime
{
    private WireMockServer _server = null!;
    private ApiClient _client = null!;
    private FakeLocalStore _local = null!;
    private DictationHistoryStore _store = null!;

    // "today" for streak math.
    private static readonly DateTimeOffset Now = new(2026, 6, 3, 12, 0, 0, TimeSpan.Zero);

    public Task InitializeAsync()
    {
        _server = WireMockServer.Start();
        _client = new ApiClient(new Uri(_server.Url!));
        _local = new FakeLocalStore();
        _store = new DictationHistoryStore(_local, _client, new FixedClock(Now));
        return Task.CompletedTask;
    }

    public Task DisposeAsync()
    {
        _client.Dispose();
        _server.Stop();
        _server.Dispose();
        return Task.CompletedTask;
    }

    private static DictationHistoryEntry Entry(int day, int words, double duration)
        => new(Guid.NewGuid(), new DateTimeOffset(2026, 6, day, 9, 0, 0, TimeSpan.Zero), "raw", null, duration, words);

    [Fact]
    public async Task ComputesTotalWordsAndAverageWpm()
    {
        _local.Seed("dictation_history", new List<DictationHistoryEntry> { Entry(3, 10, 30), Entry(3, 20, 30) });
        await _store.LoadAsync(CancellationToken.None);

        _store.TotalWords.Should().Be(30);
        _store.AverageWpm.Should().Be(30); // 30 words / (60s / 60) = 30 WPM
    }

    [Fact]
    public async Task StreakCountsConsecutiveDaysEndingToday()
    {
        _local.Seed("dictation_history", new List<DictationHistoryEntry> { Entry(3, 1, 1), Entry(2, 1, 1), Entry(1, 1, 1) });
        await _store.LoadAsync(CancellationToken.None);
        _store.StreakDays.Should().Be(3);
    }

    [Fact]
    public async Task StreakCountsFromYesterdayWhenNothingToday()
    {
        _local.Seed("dictation_history", new List<DictationHistoryEntry> { Entry(2, 1, 1), Entry(1, 1, 1) });
        await _store.LoadAsync(CancellationToken.None);
        _store.StreakDays.Should().Be(2); // today (06-03) empty, but 06-02 + 06-01 chain
    }

    [Fact]
    public async Task StreakIsZeroWhenGapBeforeYesterday()
    {
        _local.Seed("dictation_history", new List<DictationHistoryEntry> { Entry(1, 1, 1) }); // only 06-01
        await _store.LoadAsync(CancellationToken.None);
        _store.StreakDays.Should().Be(0);
    }

    [Fact]
    public async Task AddInsertsNewestFirstAndCountsWords()
    {
        await _store.AddAsync("hello brave new world", cleanedText: null, durationSeconds: 4, CancellationToken.None);
        _store.Entries.Should().ContainSingle();
        _store.Entries[0].WordCount.Should().Be(4);
        _store.TotalWords.Should().Be(4);
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
        private readonly DateTimeOffset _now;
        public FixedClock(DateTimeOffset now) => _now = now;
        public DateTimeOffset UtcNow => _now;
        public Task Delay(TimeSpan duration, CancellationToken ct) => Task.CompletedTask;
    }
}
