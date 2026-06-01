using System.Text.Json;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// Classifies a Deepgram realtime <c>Error</c> frame into a typed
/// <see cref="TranscriptionErrorCodes"/> value + a human-readable message, so the
/// reconnect wrapper and dictation/recording orchestrators can act on fatal codes
/// (auth, quota, rate-limit) instead of treating every provider error as generic.
/// Ports the macOS <c>ProviderBackedRealtimeSession.deepgramProviderError</c>
/// mapping. The message is a provider-side description (never user content), so it
/// is safe to surface.
/// </summary>
public static class DeepgramErrorClassifier
{
    public static (string Code, string Message) Classify(JsonElement root)
    {
        var rawCode = (Str(root, "error") ?? Str(root, "err_code") ?? Str(root, "type") ?? "unknown").ToLowerInvariant();
        var message = Str(root, "description") ?? Str(root, "message") ?? Str(root, "reason") ?? rawCode;

        var code = rawCode switch
        {
            "invalid_api_key" or "authentication_error" or "unauthorized" or "forbidden"
                => TranscriptionErrorCodes.AuthError,
            "insufficient_quota" or "billing_hard_limit_reached"
                => TranscriptionErrorCodes.QuotaExceeded,
            "rate_limit_exceeded" or "too_many_requests"
                => TranscriptionErrorCodes.RateLimited,
            _ => TranscriptionErrorCodes.TranscriberError,
        };

        return (code, message);
    }

    private static string? Str(JsonElement element, string property)
        => element.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
}
