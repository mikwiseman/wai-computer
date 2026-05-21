using WaiComputer.Core.Auth;

namespace WaiComputer.Linux.Auth;

public interface ILinuxSessionStore
{
    Task<Session?> LoadAsync(CancellationToken ct = default);
    Task SaveAsync(string accessToken, string? refreshToken, CancellationToken ct = default);
    Task ClearAsync(CancellationToken ct = default);
}
