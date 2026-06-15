package `is`.waiwai.computer.recording

import `is`.waiwai.computer.data.LiveTranscriptSegment
import kotlin.math.max

internal object RealtimeTranscriptSegmentFinalizer {
    fun finalizedSegments(
        providerSegments: List<LiveTranscriptSegment>,
        liveTranscript: String?,
        liveSpeaker: String? = null,
        durationSeconds: Long,
        didFinalize: Boolean,
    ): List<LiveTranscriptSegment> {
        val providerTranscript = transcriptText(providerSegments)
        val selected = RealtimeTranscriptCandidateSelector.select(
            listOf(
                providerTranscript.ifBlank { null },
                liveTranscript,
            ),
        )
        if (selected.isBlank()) return providerSegments
        if (selected == providerTranscript || normalized(selected) == normalized(providerTranscript)) {
            return providerSegments
        }

        if (!didFinalize && providerSegments.isNotEmpty()) {
            val providerTokens = RealtimeTranscriptCandidateSelector.tokenList(providerTranscript)
            val selectedTokens = RealtimeTranscriptCandidateSelector.tokenList(selected)
            if (
                selectedTokens.size > providerTokens.size &&
                selectedTokens.take(providerTokens.size) == providerTokens
            ) {
                return providerSegments
            }
        }

        if (!hasSingleProviderSpeaker(providerSegments)) {
            return providerSegments
        }

        return listOf(
            syntheticSegment(
                text = selected,
                providerSegments = providerSegments,
                liveSpeaker = liveSpeaker,
                durationSeconds = durationSeconds,
            ),
        )
    }

    private fun transcriptText(segments: List<LiveTranscriptSegment>): String = segments
        .map { it.text.trim() }
        .filter { it.isNotEmpty() }
        .joinToString(" ")

    private fun syntheticSegment(
        text: String,
        providerSegments: List<LiveTranscriptSegment>,
        liveSpeaker: String?,
        durationSeconds: Long,
    ): LiveTranscriptSegment {
        val durationMs = max(durationSeconds, 0) * 1_000
        val clampedDurationMs = durationMs.coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
        val startMs = if (providerSegments.isEmpty()) {
            max(clampedDurationMs - 1_000, 0)
        } else {
            0
        }
        val endMs = max(
            max(providerSegments.maxOfOrNull { it.endMs } ?: clampedDurationMs, clampedDurationMs),
            startMs,
        )
        val providerSpeakers = providerSegments
            .mapNotNull { it.speaker?.takeIf { speaker -> speaker.isNotEmpty() } }
            .toSet()
        val speaker = if (providerSpeakers.size == 1) providerSpeakers.single() else liveSpeaker

        return LiveTranscriptSegment(
            text = text,
            speaker = speaker,
            isFinal = true,
            startMs = startMs,
            endMs = endMs,
            confidence = 0.0,
        )
    }

    private fun normalized(text: String): String = text
        .trim()
        .split(Regex("\\s+"))
        .filter { it.isNotEmpty() }
        .joinToString(" ")
        .lowercase()

    private fun hasSingleProviderSpeaker(segments: List<LiveTranscriptSegment>): Boolean =
        segments
            .mapNotNull { it.speaker?.takeIf { speaker -> speaker.isNotEmpty() } }
            .toSet()
            .size <= 1
}
