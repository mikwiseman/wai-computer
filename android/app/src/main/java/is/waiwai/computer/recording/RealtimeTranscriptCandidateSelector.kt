package `is`.waiwai.computer.recording

internal object RealtimeTranscriptCandidateSelector {
    fun select(candidates: List<String?>): String {
        val cleaned = candidates
            .mapNotNull { candidate ->
                candidate?.trim()?.takeIf { it.isNotEmpty() }
            }
        var best = cleaned.firstOrNull() ?: return ""

        cleaned.drop(1).forEach { candidate ->
            val bestNormalized = normalized(best)
            val candidateNormalized = normalized(candidate)
            if (candidateNormalized.isEmpty()) return@forEach
            if (bestNormalized == candidateNormalized) return@forEach
            if (repeatsPrefixAfterCompleteCandidate(best, candidate)) return@forEach

            val bestTokens = tokenList(best)
            val candidateTokens = tokenList(candidate)
            if (appendsTailAfterCompleteCandidate(bestTokens, candidateTokens)) return@forEach

            when {
                candidateNormalized.contains(bestNormalized) -> best = candidate
                bestNormalized.contains(candidateNormalized) -> return@forEach
                else -> {
                    val bestTokenPhrase = bestTokens.joinToString(" ")
                    val candidateTokenPhrase = candidateTokens.joinToString(" ")
                    when {
                        bestTokenPhrase.isNotEmpty() &&
                            candidateTokenPhrase.contains(bestTokenPhrase) -> best = candidate
                        candidateTokenPhrase.isNotEmpty() &&
                            bestTokenPhrase.contains(candidateTokenPhrase) -> return@forEach
                    }
                }
            }
        }

        return best
    }

    private fun normalized(text: String): String = text
        .trim()
        .split(Regex("\\s+"))
        .filter { it.isNotEmpty() }
        .joinToString(" ")
        .lowercase()

    internal fun tokenList(text: String): List<String> = text
        .lowercase()
        .split(Regex("[^\\p{L}\\p{Nd}]+"))
        .filter { it.isNotEmpty() }

    private fun repeatsPrefixAfterCompleteCandidate(complete: String, candidate: String): Boolean {
        val completeTokens = tokenList(complete)
        val candidateTokens = tokenList(candidate)
        if (completeTokens.isEmpty() || candidateTokens.size <= completeTokens.size) return false
        if (candidateTokens.take(completeTokens.size) != completeTokens) return false
        val suffix = candidateTokens.drop(completeTokens.size)
        if (suffix.isEmpty() || suffix.size >= completeTokens.size) return false
        return completeTokens.take(suffix.size) == suffix
    }

    private fun appendsTailAfterCompleteCandidate(
        completeTokens: List<String>,
        candidateTokens: List<String>,
    ): Boolean {
        if (completeTokens.isEmpty() || candidateTokens.size <= completeTokens.size) return false
        return candidateTokens.take(completeTokens.size) == completeTokens
    }
}
