package is.waiwai.say.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class AgentChatRequest(
    val message: String,
    @SerialName("session_id") val sessionId: String? = null,
)

@Serializable
data class AgentChatResponse(
    val response: String,
    val intent: String,
    @SerialName("session_id") val sessionId: String,
    @SerialName("tool_calls") val toolCalls: Int = 0,
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
data class DigitalAgent(
    val id: String,
    val name: String,
    val description: String,
    @SerialName("schedule_type") val scheduleType: String,
    @SerialName("cron_expression") val cronExpression: String? = null,
    val status: String,
    @SerialName("run_count") val runCount: Int = 0,
    @SerialName("last_result") val lastResult: String? = null,
    @SerialName("last_error") val lastError: String? = null,
)

@Serializable
data class CreateAgentRequest(
    val description: String,
)

@Serializable
data class UserApp(
    val id: String,
    val name: String,
    @SerialName("display_name") val displayName: String,
    val description: String? = null,
    val icon: String? = null,
    val template: String? = null,
    @SerialName("app_url") val appUrl: String? = null,
    val status: String = "draft",
    val visibility: String = "private",
    @SerialName("item_count") val itemCount: Int = 0,
)

@Serializable
data class CreateAppRequest(
    val name: String,
    @SerialName("display_name") val displayName: String,
    val description: String? = null,
)

@Serializable
data class PublishAppRequest(
    val visibility: String? = null,
    @SerialName("app_url") val appUrl: String? = null,
)

@Serializable
data class RecordingSummary(
    val id: String,
    val title: String? = null,
    val type: String = "note",
    val status: String = "ready",
    @SerialName("created_at") val createdAt: String,
)
