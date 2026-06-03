using System.Diagnostics.CodeAnalysis;

namespace WaiComputer.Core.Auth;

/// <summary>
/// Parser for <c>waicomputer://auth/verify?token=...</c> magic-link URLs.
/// Identical contract to the Swift <c>MacAppState.handleIncomingURL</c>
/// validation in the macOS app. Rejects every other path/scheme so prompt
/// injection from a hostile email can't smuggle in additional commands.
/// </summary>
public static class MagicLinkUrl
{
    private const string Scheme = "waicomputer";
    private const string Host = "auth";

    public static bool TryParse(string? input, [NotNullWhen(true)] out string? token)
    {
        token = null;
        if (string.IsNullOrWhiteSpace(input)) return false;
        if (!Uri.TryCreate(input, UriKind.Absolute, out var url)) return false;

        if (!string.Equals(url.Scheme, Scheme, StringComparison.OrdinalIgnoreCase)) return false;
        if (!string.Equals(url.Host, Host, StringComparison.OrdinalIgnoreCase)) return false;

        var path = url.AbsolutePath.Trim('/');
        if (!string.Equals(path, "verify", StringComparison.OrdinalIgnoreCase)) return false;

        var raw = ExtractTokenFromQuery(url.Query);
        if (string.IsNullOrWhiteSpace(raw)) return false;

        token = raw;
        return true;
    }

    private static string? ExtractTokenFromQuery(string query)
    {
        if (string.IsNullOrEmpty(query)) return null;
        var stripped = query.StartsWith('?') ? query[1..] : query;
        foreach (var pair in stripped.Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var eq = pair.IndexOf('=');
            var key = eq < 0 ? pair : pair[..eq];
            var value = eq < 0 ? string.Empty : pair[(eq + 1)..];
            if (string.Equals(key, "token", StringComparison.OrdinalIgnoreCase))
            {
                return Uri.UnescapeDataString(value);
            }
        }
        return null;
    }
}
