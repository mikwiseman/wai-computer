using System.Text.Json.Serialization;

namespace WaiComputer.Core.Auth;

/// <summary>
/// On-disk shape of the persisted user session. Identical fields to
/// the Swift <c>Session</c> struct in <c>WaiComputerKit</c> so the macOS
/// reference (Application Support/WaiComputer/session.json) stays the
/// blueprint for the Windows file too.
/// </summary>
public sealed record Session(
    [property: JsonPropertyName("access_token")] string AccessToken,
    [property: JsonPropertyName("refresh_token")] string? RefreshToken,
    [property: JsonPropertyName("saved_at")] DateTimeOffset SavedAt);
