using FluentAssertions;
using WaiComputer.Core.Api;
using WaiComputer.Core.Api.Models;
using Xunit;

namespace WaiComputer.Core.Tests.Api;

public class TokenRefreshCoordinatorTests
{
    [Fact]
    public async Task SingleRefreshCoalescesConcurrentCallers()
    {
        var calls = 0;
        var releaseGate = new TaskCompletionSource<AuthResponse>(TaskCreationOptions.RunContinuationsAsynchronously);
        var coordinator = new TokenRefreshCoordinator(async (rt, ct) =>
        {
            Interlocked.Increment(ref calls);
            return await releaseGate.Task.ConfigureAwait(false);
        });

        const int concurrency = 64;
        var tasks = new List<Task<AuthResponse>>(concurrency);
        for (int i = 0; i < concurrency; i++)
        {
            tasks.Add(coordinator.RefreshAsync("rt", CancellationToken.None));
        }

        await Task.Delay(50);
        calls.Should().Be(1);

        var response = new AuthResponse("new-at", "new-rt", "Bearer");
        releaseGate.SetResult(response);

        var results = await Task.WhenAll(tasks);
        results.Should().AllBeEquivalentTo(response);
        calls.Should().Be(1);
    }

    [Fact]
    public async Task SecondRoundTriggersNewRefresh()
    {
        var calls = 0;
        var coordinator = new TokenRefreshCoordinator((rt, ct) =>
        {
            Interlocked.Increment(ref calls);
            return Task.FromResult(new AuthResponse($"at-{calls}", "rt", "Bearer"));
        });

        var first = await coordinator.RefreshAsync("rt", CancellationToken.None);
        var second = await coordinator.RefreshAsync("rt", CancellationToken.None);

        first.AccessToken.Should().Be("at-1");
        second.AccessToken.Should().Be("at-2");
        calls.Should().Be(2);
    }

    [Fact]
    public async Task FailurePropagatesToAllConcurrentCallers()
    {
        var releaseGate = new TaskCompletionSource<AuthResponse>(TaskCreationOptions.RunContinuationsAsynchronously);
        var coordinator = new TokenRefreshCoordinator(async (rt, ct) =>
            await releaseGate.Task.ConfigureAwait(false));

        var tasks = Enumerable.Range(0, 8)
            .Select(_ => coordinator.RefreshAsync("rt", CancellationToken.None))
            .ToList();

        releaseGate.SetException(new InvalidOperationException("refresh failed"));

        foreach (var t in tasks)
        {
            var act = async () => await t;
            await act.Should().ThrowAsync<InvalidOperationException>().WithMessage("refresh failed");
        }
    }
}
