using WaiComputer.Core.Api.Models;

namespace WaiComputer.Core.Api;

/// <summary>
/// Coalesces concurrent 401-driven refresh attempts into a single in-flight
/// request. Mirrors the Swift <c>APIClient</c>'s <c>refreshWaiters</c> pattern.
/// </summary>
internal sealed class TokenRefreshCoordinator
{
    private readonly Func<string, CancellationToken, Task<AuthResponse>> _refresh;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private Task<AuthResponse>? _inFlight;

    public TokenRefreshCoordinator(Func<string, CancellationToken, Task<AuthResponse>> refresh)
    {
        _refresh = refresh ?? throw new ArgumentNullException(nameof(refresh));
    }

    /// <summary>
    /// Returns the result of the refresh — either the one started by this caller,
    /// or the one already in flight from a concurrent caller. Exactly one network
    /// request is made regardless of how many concurrent callers arrive.
    /// </summary>
    public async Task<AuthResponse> RefreshAsync(string refreshToken, CancellationToken ct)
    {
        Task<AuthResponse> task;
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (_inFlight is { IsCompleted: false } existing)
            {
                task = existing;
            }
            else
            {
                _inFlight = StartRefreshAsync(refreshToken, ct);
                task = _inFlight;
            }
        }
        finally
        {
            _gate.Release();
        }

        try
        {
            return await task.ConfigureAwait(false);
        }
        finally
        {
            await _gate.WaitAsync(CancellationToken.None).ConfigureAwait(false);
            try
            {
                if (ReferenceEquals(_inFlight, task))
                {
                    _inFlight = null;
                }
            }
            finally
            {
                _gate.Release();
            }
        }
    }

    private async Task<AuthResponse> StartRefreshAsync(string refreshToken, CancellationToken ct)
    {
        // Force a real Task scheduling boundary so concurrent waiters can attach
        // before the network round-trip starts.
        await Task.Yield();
        return await _refresh(refreshToken, ct).ConfigureAwait(false);
    }
}
