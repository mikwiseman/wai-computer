namespace WaiComputer.Core.Api.Models;

/// <summary>
/// Renders a raw diarization speaker label (e.g. <c>"speaker_0"</c>, <c>"you"</c>,
/// or a real person name) into user-facing copy, localized for EN/RU. Ports the
/// macOS <c>SpeakerLabelCopy</c> so every WaiComputer client shows identical
/// speaker names. The numeric suffix is preserved verbatim (no +1):
/// <c>"speaker_0"</c> renders as <c>"Speaker 0"</c> / <c>"Говорящий 0"</c>.
/// </summary>
public static class SpeakerLabelCopy
{
    /// <summary>
    /// Localized display label, or <c>null</c> when the raw label is null/blank.
    /// </summary>
    public static string? UserFacingLabel(string? rawLabel, string? languageCode)
    {
        if (rawLabel is null)
        {
            return null;
        }

        var trimmed = rawLabel.Trim();
        if (trimmed.Length == 0)
        {
            return null;
        }

        var russian = PrefersRussian(languageCode);
        var normalized = trimmed.ToLowerInvariant();

        if (normalized == "you")
        {
            return russian ? "Ты" : "You";
        }

        if (normalized == "speaker")
        {
            return russian ? "Говорящий" : "Speaker";
        }

        var suffix = GenericSpeakerSuffix(trimmed);
        if (suffix is not null)
        {
            return russian ? $"Говорящий {suffix}" : $"Speaker {suffix}";
        }

        // A real name (e.g. "Оля") — return it unchanged.
        return trimmed;
    }

    private static bool PrefersRussian(string? languageCode)
        => languageCode is not null
           && languageCode.Trim().StartsWith("ru", StringComparison.OrdinalIgnoreCase);

    private static string? GenericSpeakerSuffix(string rawLabel)
    {
        var lower = rawLabel.ToLowerInvariant();
        foreach (var prefix in new[] { "speaker ", "speaker_", "speaker-" })
        {
            if (lower.StartsWith(prefix, StringComparison.Ordinal))
            {
                var suffix = rawLabel[prefix.Length..].Trim();
                return suffix.Length > 0 ? suffix : null;
            }
        }

        return null;
    }
}
