using System.Text.Json;
using WaiComputer.Core.Api;
using WaiComputer.Core.Auth;
using WaiComputer.Linux.Platform;

namespace WaiComputer.Linux.Auth;

public sealed class LinuxSecretServiceException : Exception
{
    public LinuxSecretServiceException(string message) : base(message)
    {
    }
}

public sealed class LinuxSecretServiceSessionStore : ILinuxSessionStore
{
    private static readonly string[] SecretAttributes = ["app", "wai-computer", "session", "default"];
    private readonly ICommandRunner _commands;

    public LinuxSecretServiceSessionStore(ICommandRunner commands)
    {
        _commands = commands;
    }

    public async Task<Session?> LoadAsync(CancellationToken ct = default)
    {
        var result = await _commands.RunAsync("secret-tool", ["lookup", .. SecretAttributes], ct: ct).ConfigureAwait(false);
        if (result.ExitCode == 1 && string.IsNullOrWhiteSpace(result.Stdout))
        {
            return null;
        }
        if (!result.Succeeded)
        {
            throw new LinuxSecretServiceException($"Secret Service lookup failed: {result.Stderr.Trim()}");
        }

        try
        {
            var session = JsonSerializer.Deserialize<Session>(result.Stdout, WaiJson.Options);
            if (session is null || string.IsNullOrWhiteSpace(session.AccessToken))
            {
                throw new LinuxSecretServiceException("Secret Service returned an empty WaiComputer session.");
            }

            return session;
        }
        catch (JsonException ex)
        {
            throw new LinuxSecretServiceException($"Secret Service returned malformed session JSON: {ex.Message}");
        }
    }

    public async Task SaveAsync(string accessToken, string? refreshToken, CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(accessToken))
        {
            throw new ArgumentException("Access token must not be empty.", nameof(accessToken));
        }

        var payload = JsonSerializer.Serialize(new Session(accessToken, refreshToken, DateTimeOffset.UtcNow), WaiJson.Options);
        var result = await _commands.RunAsync(
            "secret-tool",
            ["store", "--label", "WaiComputer session", .. SecretAttributes],
            payload,
            ct).ConfigureAwait(false);

        if (!result.Succeeded)
        {
            throw new LinuxSecretServiceException($"Secret Service save failed: {result.Stderr.Trim()}");
        }
    }

    public async Task ClearAsync(CancellationToken ct = default)
    {
        var result = await _commands.RunAsync("secret-tool", ["clear", .. SecretAttributes], ct: ct).ConfigureAwait(false);
        if (result.ExitCode is 0 or 1)
        {
            return;
        }

        throw new LinuxSecretServiceException($"Secret Service clear failed: {result.Stderr.Trim()}");
    }
}
