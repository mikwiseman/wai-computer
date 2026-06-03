using System.Text.Json.Serialization;

namespace WaiComputer.Core.Api.Models;

public sealed record User(
    string Id,
    string Email,
    DateTimeOffset CreatedAt,
    [property: JsonPropertyName("has_password")] bool HasPassword);

public sealed record AuthResponse(
    [property: JsonPropertyName("access_token")] string AccessToken,
    [property: JsonPropertyName("refresh_token")] string? RefreshToken,
    [property: JsonPropertyName("token_type")] string TokenType);

public sealed record MessageResponse(string Message);

public sealed record RegisterRequest(string Email, string Password);
public sealed record LoginRequest(string Email, string Password);
public sealed record MagicLinkRequest(string Email, string? Client);
public sealed record VerifyMagicLinkRequest(string Token);
public sealed record RefreshTokenRequest(
    [property: JsonPropertyName("refresh_token")] string RefreshToken);
public sealed record LogoutRequest(
    [property: JsonPropertyName("refresh_token")] string? RefreshToken);
public sealed record ChangePasswordRequest(
    [property: JsonPropertyName("current_password")] string CurrentPassword,
    [property: JsonPropertyName("new_password")] string NewPassword);
