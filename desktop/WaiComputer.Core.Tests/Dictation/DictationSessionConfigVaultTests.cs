using System;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using WaiComputer.Core.Api.Models;
using WaiComputer.Core.Dictation;
using WaiComputer.Core.Time;
using Xunit;

namespace WaiComputer.Core.Tests.Dictation;

public class DictationSessionConfigVaultTests
{
    private static readonly VaultKey Key = new("en", 1, "dictation");

    private static RealtimeTranscriptionSessionConfig Config(
        string language = "en", string model = "nova-3", int expiresInSeconds = 60)
        => new(RealtimeProvider.Deepgram, "tok", expiresInSeconds, 16000, "linear16", language, 1, model,
            null, null, false, "wss://wai.computer/api/transcription/stream", AuthScheme.Bearer);

    [Fact]
    public async Task TakeMintsFreshWhenEmpty()
    {
        var minter = new CountingMinter(_ => Config());
        var vault = new DictationSessionConfigVault(minter.Mint, new AdvanceableClock());

        var result = await vault.TakeAsync(Key, ct: CancellationToken.None);

        result.Prefetched.Should().BeFalse();
        result.TokenAgeMilliseconds.Should().Be(0);
        minter.Calls.Should().Be(1);
    }

    [Fact]
    public async Task PrefetchThenTakeReturnsCachedWithoutReminting()
    {
        var minter = new CountingMinter(_ => Config());
        var vault = new DictationSessionConfigVault(minter.Mint, new AdvanceableClock());

        vault.Prefetch(Key);
        await WaitFor(() => minter.Calls == 1);

        var result = await vault.TakeAsync(Key, ct: CancellationToken.None);

        result.Prefetched.Should().BeTrue();
        minter.Calls.Should().Be(1); // served from the prefetch — no second mint
    }

    [Fact]
    public async Task CacheIsConsumedOnTake()
    {
        var minter = new CountingMinter(_ => Config());
        var vault = new DictationSessionConfigVault(minter.Mint, new AdvanceableClock());

        vault.Prefetch(Key);
        await WaitFor(() => minter.Calls == 1);

        var first = await vault.TakeAsync(Key, ct: CancellationToken.None);
        var second = await vault.TakeAsync(Key, ct: CancellationToken.None);

        first.Prefetched.Should().BeTrue();
        second.Prefetched.Should().BeFalse(); // cache consumed -> minted fresh
        minter.Calls.Should().Be(2);
    }

    [Fact]
    public async Task ExpiredCacheIsNotReturned()
    {
        var clock = new AdvanceableClock();
        var minter = new CountingMinter(_ => Config(expiresInSeconds: 8)); // safety = max(3, 8/4)=3 -> alive 5s
        var vault = new DictationSessionConfigVault(minter.Mint, clock);

        vault.Prefetch(Key);
        await WaitFor(() => minter.Calls == 1);

        clock.Advance(TimeSpan.FromSeconds(6)); // past the 5s alive window

        var result = await vault.TakeAsync(Key, ct: CancellationToken.None);
        result.Prefetched.Should().BeFalse();
        minter.Calls.Should().Be(2);
    }

    [Fact]
    public async Task LanguageMismatchThrows()
    {
        var minter = new CountingMinter(_ => Config(language: "es"));
        var vault = new DictationSessionConfigVault(minter.Mint, new AdvanceableClock());

        var act = () => vault.TakeAsync(Key, ct: CancellationToken.None);
        await act.Should().ThrowAsync<DictationSessionConfigVaultException>()
            .WithMessage("*language mismatch*");
    }

    [Fact]
    public async Task ProviderModelMismatchThrows()
    {
        var minter = new CountingMinter(_ => Config(model: "nova-2"));
        var vault = new DictationSessionConfigVault(minter.Mint, new AdvanceableClock());

        var act = () => vault.TakeAsync(Key, expectedModel: "nova-3", ct: CancellationToken.None);
        await act.Should().ThrowAsync<DictationSessionConfigVaultException>()
            .WithMessage("*provider/model mismatch*");
    }

    [Fact]
    public async Task ClearDropsCache()
    {
        var minter = new CountingMinter(_ => Config());
        var vault = new DictationSessionConfigVault(minter.Mint, new AdvanceableClock());

        vault.Prefetch(Key);
        await WaitFor(() => minter.Calls == 1);
        vault.Clear();

        var result = await vault.TakeAsync(Key, ct: CancellationToken.None);
        result.Prefetched.Should().BeFalse(); // cache cleared -> minted fresh
        minter.Calls.Should().Be(2);
    }

    [Fact]
    public async Task InFlightPrefetchIsCoalescedIntoTake()
    {
        var gate = new TaskCompletionSource();
        var minter = new CountingMinter(async _ => { await gate.Task; return Config(); });
        var vault = new DictationSessionConfigVault(minter.Mint, new AdvanceableClock());

        vault.Prefetch(Key);                                   // starts a mint that blocks on the gate
        await WaitFor(() => minter.Calls == 1);
        var takeTask = vault.TakeAsync(Key, ct: CancellationToken.None); // must await the in-flight, not start a 2nd mint

        await Task.Delay(50);
        takeTask.IsCompleted.Should().BeFalse();               // still waiting on the gated mint
        gate.SetResult();

        var result = await takeTask;
        result.Prefetched.Should().BeTrue();
        minter.Calls.Should().Be(1);                           // single mint shared by prefetch + take
    }

    private static async Task WaitFor(Func<bool> condition, int timeoutMs = 2000)
    {
        var start = Environment.TickCount64;
        while (Environment.TickCount64 - start < timeoutMs)
        {
            if (condition()) return;
            await Task.Delay(5);
        }
        throw new TimeoutException("Condition not met within timeout.");
    }

    private sealed class CountingMinter
    {
        private readonly Func<VaultKey, Task<RealtimeTranscriptionSessionConfig>> _impl;
        private int _calls;
        public int Calls => Volatile.Read(ref _calls);

        public CountingMinter(Func<VaultKey, RealtimeTranscriptionSessionConfig> sync)
            => _impl = k => Task.FromResult(sync(k));
        public CountingMinter(Func<VaultKey, Task<RealtimeTranscriptionSessionConfig>> asyncImpl)
            => _impl = asyncImpl;

        public Task<RealtimeTranscriptionSessionConfig> Mint(VaultKey key, CancellationToken ct)
        {
            Interlocked.Increment(ref _calls);
            return _impl(key);
        }
    }

    private sealed class AdvanceableClock : ISystemClock
    {
        private DateTimeOffset _now = new(2026, 6, 1, 12, 0, 0, TimeSpan.Zero);
        public DateTimeOffset UtcNow => _now;
        public void Advance(TimeSpan by) => _now = _now.Add(by);
        public Task Delay(TimeSpan duration, CancellationToken ct) => Task.CompletedTask;
    }
}
