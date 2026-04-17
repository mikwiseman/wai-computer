package `is`.waiwai.say.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
enum class RecordingType {
    meeting,
    note,
    reflection,
}

@Serializable
enum class RecordingStatus {
    @SerialName("pending_upload")
    PendingUpload,

    @SerialName("uploading")
    Uploading,

    @SerialName("processing")
    Processing,

    @SerialName("ready")
    Ready,

    @SerialName("failed")
    Failed,
}

@Serializable
data class UserSummary(
    val id: String,
    val email: String,
    @SerialName("created_at") val createdAt: String,
)

@Serializable
data class AuthTokenPair(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String,
    @SerialName("token_type") val tokenType: String = "bearer",
)

@Serializable
data class MessageResponse(
    val message: String,
)

@Serializable
data class LoginRequest(
    val email: String,
    val password: String,
)

@Serializable
data class RegisterRequest(
    val email: String,
    val password: String,
)

@Serializable
data class MagicLinkRequest(
    val email: String,
    val client: String? = null,
)

@Serializable
data class VerifyMagicLinkRequest(
    val token: String,
)

@Serializable
data class RefreshRequest(
    @SerialName("refresh_token") val refreshToken: String,
)

@Serializable
data class LogoutRequest(
    @SerialName("refresh_token") val refreshToken: String? = null,
)

@Serializable
data class Folder(
    val id: String,
    val name: String,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class Recording(
    val id: String,
    val title: String? = null,
    val type: RecordingType = RecordingType.note,
    @SerialName("audio_url") val audioUrl: String? = null,
    val status: RecordingStatus = RecordingStatus.PendingUpload,
    @SerialName("failure_code") val failureCode: String? = null,
    @SerialName("failure_message") val failureMessage: String? = null,
    @SerialName("uploaded_at") val uploadedAt: String? = null,
    @SerialName("duration_seconds") val durationSeconds: Int? = null,
    val language: String? = null,
    @SerialName("folder_id") val folderId: String? = null,
    @SerialName("deleted_at") val deletedAt: String? = null,
    @SerialName("starred_at") val starredAt: String? = null,
    @SerialName("created_at") val createdAt: String,
)

@Serializable
data class RecordingDetail(
    val id: String,
    val title: String? = null,
    val type: RecordingType = RecordingType.note,
    @SerialName("audio_url") val audioUrl: String? = null,
    val status: RecordingStatus = RecordingStatus.PendingUpload,
    @SerialName("failure_code") val failureCode: String? = null,
    @SerialName("failure_message") val failureMessage: String? = null,
    @SerialName("uploaded_at") val uploadedAt: String? = null,
    @SerialName("duration_seconds") val durationSeconds: Int? = null,
    val language: String? = null,
    @SerialName("folder_id") val folderId: String? = null,
    @SerialName("deleted_at") val deletedAt: String? = null,
    @SerialName("starred_at") val starredAt: String? = null,
    @SerialName("created_at") val createdAt: String,
    val segments: List<Segment> = emptyList(),
    val summary: Summary? = null,
    @SerialName("action_items") val actionItems: List<ActionItem> = emptyList(),
    val highlights: List<RecordingHighlight> = emptyList(),
)

@Serializable
data class Segment(
    val id: String,
    val speaker: String? = null,
    val content: String,
    @SerialName("start_ms") val startMs: Int? = null,
    @SerialName("end_ms") val endMs: Int? = null,
    val confidence: Double? = null,
)

@Serializable
data class Summary(
    val summary: String? = null,
    @SerialName("key_points") val keyPoints: List<String>? = null,
    val decisions: List<Decision>? = null,
    val topics: List<String>? = null,
    @SerialName("people_mentioned") val peopleMentioned: List<String>? = null,
    val sentiment: String? = null,
)

@Serializable
data class Decision(
    val decision: String,
    val context: String? = null,
)

@Serializable
data class ActionItem(
    val id: String,
    @SerialName("recording_id") val recordingId: String? = null,
    val task: String,
    val owner: String? = null,
    @SerialName("due_date") val dueDate: String? = null,
    val priority: ActionItemPriority? = null,
    val status: ActionItemStatus = ActionItemStatus.Pending,
    val source: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
enum class ActionItemPriority {
    high,
    medium,
    low,
}

@Serializable
enum class ActionItemStatus {
    @SerialName("pending")
    Pending,

    @SerialName("in_progress")
    InProgress,

    @SerialName("completed")
    Completed,

    @SerialName("cancelled")
    Cancelled,
}

@Serializable
data class RecordingHighlight(
    val id: String,
    @SerialName("recording_id") val recordingId: String,
    val category: String,
    val title: String,
    val description: String? = null,
    val speaker: String? = null,
    @SerialName("start_ms") val startMs: Int? = null,
    @SerialName("end_ms") val endMs: Int? = null,
    val importance: String,
)

@Serializable
data class CreateRecordingRequest(
    val title: String? = null,
    val type: RecordingType = RecordingType.note,
    val language: String? = null,
    @SerialName("folder_id") val folderId: String? = null,
)

@Serializable
data class UpdateRecordingRequest(
    val title: String? = null,
    val type: RecordingType? = null,
    @SerialName("folder_id") val folderId: String? = null,
)

@Serializable
data class UpdateActionItemRequest(
    val status: ActionItemStatus,
)

@Serializable
data class QARequest(
    val question: String,
    @SerialName("recording_ids") val recordingIds: List<String>? = null,
)

@Serializable
data class QAResponse(
    val answer: String,
    val sources: List<QASource> = emptyList(),
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
data class CreateRealtimeTranscriptionSessionRequest(
    val language: String = "multi",
    val channels: Int = 1,
)

@Serializable
data class RealtimeTranscriptionSessionConfig(
    val provider: String,
    val token: String,
    @SerialName("expires_in_seconds") val expiresInSeconds: Int,
    @SerialName("sample_rate") val sampleRate: Int,
    @SerialName("audio_format") val audioFormat: String,
    val language: String,
    val channels: Int,
    val model: String,
    @SerialName("keep_alive_interval_seconds") val keepAliveIntervalSeconds: Int? = null,
    @SerialName("commit_strategy") val commitStrategy: String? = null,
)

@Serializable
data class LiveTranscriptSegment(
    val text: String,
    val speaker: String? = null,
    @SerialName("is_final") val isFinal: Boolean = true,
    @SerialName("start_ms") val startMs: Int = 0,
    @SerialName("end_ms") val endMs: Int = 0,
    val confidence: Double = 1.0,
)

@Serializable
data class TranscriptSegmentPayload(
    val text: String,
    val speaker: String? = null,
    @SerialName("start_ms") val startMs: Int = 0,
    @SerialName("end_ms") val endMs: Int = 0,
    val confidence: Double? = null,
)

@Serializable
data class SaveTranscriptRequest(
    val segments: List<TranscriptSegmentPayload>,
    @SerialName("duration_seconds") val durationSeconds: Int? = null,
)
