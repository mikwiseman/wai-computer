package `is`.waiwai.computer.recording

import `is`.waiwai.computer.data.LiveTranscriptSegment
import org.junit.Assert.assertEquals
import org.junit.Test

class RealtimeTranscriptSegmentFinalizerTest {
    @Test
    fun `prefers fuller live transcript when provider final dropped startup words`() {
        val providerSegments = listOf(
            LiveTranscriptSegment(
                text = "check fast startup",
                speaker = "speaker_0",
                isFinal = true,
                startMs = 800,
                endMs = 2_400,
                confidence = 0.92,
            ),
        )

        val segments = RealtimeTranscriptSegmentFinalizer.finalizedSegments(
            providerSegments = providerSegments,
            liveTranscript = "today we check fast startup",
            durationSeconds = 3,
            didFinalize = true,
        )

        assertEquals(listOf("today we check fast startup"), segments.map { it.text })
        assertEquals("speaker_0", segments.single().speaker)
        assertEquals(0, segments.single().startMs)
        assertEquals(3_000, segments.single().endMs)
    }

    @Test
    fun `keeps provider segments when live transcript only adds unfinalized tail`() {
        val providerSegments = listOf(
            LiveTranscriptSegment(
                text = "send the report",
                isFinal = true,
                startMs = 0,
                endMs = 1_500,
                confidence = 0.93,
            ),
        )

        val segments = RealtimeTranscriptSegmentFinalizer.finalizedSegments(
            providerSegments = providerSegments,
            liveTranscript = "send the report to",
            durationSeconds = 2,
            didFinalize = false,
        )

        assertEquals(listOf("send the report"), segments.map { it.text })
        assertEquals(1_500, segments.single().endMs)
    }

    @Test
    fun `creates live segment when provider returned no segments`() {
        val segments = RealtimeTranscriptSegmentFinalizer.finalizedSegments(
            providerSegments = emptyList(),
            liveTranscript = "only live text survived",
            liveSpeaker = "speaker_1",
            durationSeconds = 4,
            didFinalize = false,
        )

        assertEquals(listOf("only live text survived"), segments.map { it.text })
        assertEquals("speaker_1", segments.single().speaker)
        assertEquals(3_000, segments.single().startMs)
        assertEquals(4_000, segments.single().endMs)
    }

    @Test
    fun `preserves provider segments when fuller live transcript would collapse multiple speakers`() {
        val providerSegments = listOf(
            LiveTranscriptSegment(
                text = "can you review this",
                speaker = "speaker_0",
                isFinal = true,
                startMs = 900,
                endMs = 2_100,
                confidence = 0.9,
            ),
            LiveTranscriptSegment(
                text = "yes today",
                speaker = "speaker_1",
                isFinal = true,
                startMs = 2_200,
                endMs = 3_100,
                confidence = 0.91,
            ),
        )

        val segments = RealtimeTranscriptSegmentFinalizer.finalizedSegments(
            providerSegments = providerSegments,
            liveTranscript = "alex can you review this yes today",
            durationSeconds = 4,
            didFinalize = true,
        )

        assertEquals(listOf("can you review this", "yes today"), segments.map { it.text })
        assertEquals(listOf("speaker_0", "speaker_1"), segments.map { it.speaker })
    }
}
