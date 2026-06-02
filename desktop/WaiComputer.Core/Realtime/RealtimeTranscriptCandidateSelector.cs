using System.Linq;

namespace WaiComputer.Core.Realtime;

/// <summary>
/// Picks the most complete transcript from the provider's close output, provider
/// deltas, and the UI accumulator. Short dictation sessions can finalize while
/// the last live/interim text is still fuller than the provider's drained
/// segment list, so this prefers completeness over source order. Ports the macOS
/// <c>RealtimeTranscriptCandidateSelector</c>.
/// </summary>
public static class RealtimeTranscriptCandidateSelector
{
    public static string Select(IEnumerable<string?> candidates)
    {
        var cleaned = candidates
            .Select(c => c?.Trim() ?? string.Empty)
            .Where(c => c.Length > 0)
            .ToList();
        if (cleaned.Count == 0)
        {
            return string.Empty;
        }

        var best = cleaned[0];
        foreach (var candidate in cleaned.Skip(1))
        {
            var bestNormalized = Normalize(best);
            var candidateNormalized = Normalize(candidate);
            if (candidateNormalized.Length == 0 || bestNormalized == candidateNormalized)
            {
                continue;
            }
            if (candidateNormalized.Contains(bestNormalized, StringComparison.Ordinal))
            {
                best = candidate; // candidate is a superset — more complete
            }
            // else best contains candidate (keep best), or unrelated (keep best)
        }

        return best;
    }

    private static string Normalize(string text)
        => string.Join(' ', text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)).ToLowerInvariant();
}
