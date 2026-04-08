package `is`.waiwai.say.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable


@Serializable
data class QARequest(
    val question: String,
    @SerialName("recording_ids") val recordingIds: List<String>? = null,
)

@Serializable
data class QASource(
    @SerialName("segment_id") val segmentId: String,
    @SerialName("recording_id") val recordingId: String,
    @SerialName("recording_title") val recordingTitle: String? = null,
    val speaker: String? = null,
    val content: String,
    @SerialName("start_ms") val startMs: Int? = null,
    @SerialName("end_ms") val endMs: Int? = null,
)

@Serializable
data class QAResponse(
    val answer: String,
    val sources: List<QASource> = emptyList(),
)

@Serializable
data class RealtimeVoiceSessionRequest(
    val mode: String = "conversation",
)

@Serializable
data class RealtimeVoiceSession(
    val provider: String,
    val mode: String,
    @SerialName("agent_id") val agentId: String,
    @SerialName("signed_url") val signedUrl: String,
    @SerialName("expires_in_seconds") val expiresInSeconds: Int,
    val environment: String? = null,
    @SerialName("branch_id") val branchId: String? = null,
)

@Serializable
data class RecordingSummary(
    val id: String,
    val title: String? = null,
    val type: String = "note",
    val status: String = "ready",
    @SerialName("created_at") val createdAt: String,
)
