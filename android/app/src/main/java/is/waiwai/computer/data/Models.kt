package `is`.waiwai.computer.data

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
    @SerialName("has_password") val hasPassword: Boolean = true,
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
    @SerialName("raw_label") val rawLabel: String? = null,
    @SerialName("person_id") val personId: String? = null,
    @SerialName("display_name") val displayName: String? = null,
    @SerialName("auto_assigned") val autoAssigned: Boolean = false,
    @SerialName("match_confidence") val matchConfidence: Double? = null,
    val content: String,
    @SerialName("start_ms") val startMs: Int? = null,
    @SerialName("end_ms") val endMs: Int? = null,
    val confidence: Double? = null,
)

@Serializable
data class Person(
    val id: String,
    @SerialName("display_name") val displayName: String,
    val color: String? = null,
    val aliases: List<String>? = null,
    @SerialName("voiceprint_count") val voiceprintCount: Int = 0,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
)

@Serializable
data class CreatePersonRequest(
    @SerialName("display_name") val displayName: String,
    val color: String? = null,
)

@Serializable
data class AssignSpeakerRequest(
    @SerialName("raw_label") val rawLabel: String,
    @SerialName("person_id") val personId: String? = null,
    @SerialName("new_display_name") val newDisplayName: String? = null,
)

@Serializable
data class VoiceEnrollmentResponse(
    val person: Person,
    @SerialName("voiceprint_id") val voiceprintId: String,
    @SerialName("duration_s") val durationS: Double,
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
data class UserSettings(
    @SerialName("default_language") val defaultLanguage: String,
    @SerialName("summary_language") val summaryLanguage: String,
    @SerialName("summary_style") val summaryStyle: String,
    @SerialName("summary_instructions") val summaryInstructions: String? = null,
    @SerialName("dictation_live_stt_provider") val dictationLiveSttProvider: String = "soniox",
    @SerialName("dictation_live_stt_model") val dictationLiveSttModel: String = "stt-rt-v4",
    @SerialName("recording_live_stt_provider") val recordingLiveSttProvider: String = "elevenlabs",
    @SerialName("recording_live_stt_model") val recordingLiveSttModel: String = "scribe_v2_realtime",
    @SerialName("file_stt_provider") val fileSttProvider: String = "elevenlabs",
    @SerialName("file_stt_model") val fileSttModel: String = "scribe_v2",
    @SerialName("dictation_post_filter_enabled") val dictationPostFilterEnabled: Boolean = false,
    @SerialName("dictation_post_filter_provider") val dictationPostFilterProvider: String = "openai",
    @SerialName("dictation_post_filter_model") val dictationPostFilterModel: String = "gpt-5.5",
)

@Serializable
data class UpdateSettingsRequest(
    @SerialName("default_language") val defaultLanguage: String? = null,
    @SerialName("summary_language") val summaryLanguage: String? = null,
    @SerialName("summary_style") val summaryStyle: String? = null,
    @SerialName("summary_instructions") val summaryInstructions: String? = null,
    @SerialName("dictation_live_stt_provider") val dictationLiveSttProvider: String? = null,
    @SerialName("dictation_live_stt_model") val dictationLiveSttModel: String? = null,
    @SerialName("recording_live_stt_provider") val recordingLiveSttProvider: String? = null,
    @SerialName("recording_live_stt_model") val recordingLiveSttModel: String? = null,
    @SerialName("file_stt_provider") val fileSttProvider: String? = null,
    @SerialName("file_stt_model") val fileSttModel: String? = null,
    @SerialName("dictation_post_filter_enabled") val dictationPostFilterEnabled: Boolean? = null,
    @SerialName("dictation_post_filter_provider") val dictationPostFilterProvider: String? = null,
    @SerialName("dictation_post_filter_model") val dictationPostFilterModel: String? = null,
)

@Serializable
data class TranscriptionModelOption(
    val provider: String,
    val model: String,
    val label: String,
    val description: String,
) {
    val id: String get() = "$provider:$model"
}

@Serializable
data class TranscriptionOptions(
    @SerialName("dictation_live_stt") val dictationLiveStt: List<TranscriptionModelOption>,
    @SerialName("recording_live_stt") val recordingLiveStt: List<TranscriptionModelOption>,
    @SerialName("file_stt") val fileStt: List<TranscriptionModelOption>,
    @SerialName("dictation_post_filter") val dictationPostFilter: List<TranscriptionModelOption>,
)

@Serializable
data class CompanionScope(
    @SerialName("recording_ids") val recordingIds: List<String>? = null,
    @SerialName("folder_ids") val folderIds: List<String>? = null,
    val types: List<String>? = null,
    val speakers: List<String>? = null,
    @SerialName("date_from") val dateFrom: String? = null,
    @SerialName("date_to") val dateTo: String? = null,
)

@Serializable
data class CompanionConversation(
    val id: String,
    val title: String? = null,
    val scope: CompanionScope? = null,
    @SerialName("pinned_at") val pinnedAt: String? = null,
    @SerialName("last_message_at") val lastMessageAt: String? = null,
    @SerialName("archived_at") val archivedAt: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
)

@Serializable
data class CompanionConversationList(
    val chats: List<CompanionConversation> = emptyList(),
)

@Serializable
data class CompanionCitation(
    val id: String,
    @SerialName("segment_id") val segmentId: String? = null,
    @SerialName("recording_id") val recordingId: String? = null,
    @SerialName("span_start") val spanStart: Int,
    @SerialName("span_end") val spanEnd: Int,
    @SerialName("citation_index") val citationIndex: Int,
)

@Serializable
data class CompanionMessage(
    val id: String,
    val role: String,
    val content: kotlinx.serialization.json.JsonElement,
    @SerialName("tool_calls") val toolCalls: kotlinx.serialization.json.JsonElement? = null,
    val citations: List<CompanionCitation> = emptyList(),
    val model: String? = null,
    @SerialName("input_tokens") val inputTokens: Int? = null,
    @SerialName("output_tokens") val outputTokens: Int? = null,
    @SerialName("cached_tokens") val cachedTokens: Int? = null,
    @SerialName("latency_ms") val latencyMs: Int? = null,
    @SerialName("created_at") val createdAt: String,
)

@Serializable
data class CompanionConversationDetail(
    val id: String,
    val title: String? = null,
    val scope: CompanionScope? = null,
    @SerialName("pinned_at") val pinnedAt: String? = null,
    @SerialName("last_message_at") val lastMessageAt: String? = null,
    @SerialName("archived_at") val archivedAt: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
    val messages: List<CompanionMessage> = emptyList(),
)

@Serializable
data class CreateCompanionChatRequest(val scope: CompanionScope? = null)

@Serializable
data class PatchCompanionChatRequest(
    val title: String? = null,
    val scope: CompanionScope? = null,
    val pinned: Boolean? = null,
    val archived: Boolean? = null,
)

@Serializable
data class PostCompanionMessageRequest(val content: String)

@Serializable
data class CreateRealtimeTranscriptionSessionRequest(
    val language: String = "multi",
    val channels: Int = 1,
    val purpose: String = "recording",
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
    @SerialName("no_verbatim") val noVerbatim: Boolean = false,
    @SerialName("websocket_url") val websocketUrl: String? = null,
    @SerialName("auth_scheme") val authScheme: String = "query_token",
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

@Serializable
data class SearchResult(
    @SerialName("recording_id") val recordingId: String,
    @SerialName("recording_title") val recordingTitle: String? = null,
    @SerialName("recording_type") val recordingType: String,
    @SerialName("segment_id") val segmentId: String,
    val speaker: String? = null,
    val content: String,
    @SerialName("start_ms") val startMs: Int? = null,
    @SerialName("end_ms") val endMs: Int? = null,
    val score: Double,
)

@Serializable
data class SearchResponse(
    val results: List<SearchResult> = emptyList(),
    val total: Int = 0,
)

enum class SearchMode(val pathSuffix: String) {
    Hybrid(""),
    Semantic("/semantic"),
    Fulltext("/fts"),
}

@Serializable
data class UpdatePersonRequest(
    @SerialName("display_name") val displayName: String? = null,
    val color: String? = null,
    val aliases: List<String>? = null,
)

@Serializable
data class CreateFolderRequest(
    val name: String,
)

@Serializable
data class UpdateFolderRequest(
    val name: String,
)
