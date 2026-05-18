package `is`.waiwai.computer.data

import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.utils.io.readUTF8Line
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/// Typed events emitted by the Companion SSE stream.
sealed interface CompanionStreamEvent {
    data class TurnStart(val messageId: String, val conversationId: String) : CompanionStreamEvent
    data class ToolCall(val callId: String, val tool: String) : CompanionStreamEvent
    data class ToolResult(val callId: String, val summary: String) : CompanionStreamEvent
    data class Token(val text: String) : CompanionStreamEvent
    data class Citation(
        val index: Int,
        val segmentId: String,
        val recordingId: String,
        val startMs: Int?,
        val endMs: Int?,
        val spanStart: Int,
        val spanEnd: Int,
    ) : CompanionStreamEvent
    data class Done(val messageId: String, val model: String, val latencyMs: Int) : CompanionStreamEvent
    data class Error(val code: String, val message: String) : CompanionStreamEvent
}

class CompanionApi(
    private val transport: ApiTransport,
    private val authStore: AuthStoreContract,
    private val json: Json = defaultJson,
) {
    suspend fun createChat(scope: CompanionScope? = null): CompanionConversation =
        authorizedRequest(
            method = HttpMethod.Post,
            path = "/api/companion/chats",
            body = CreateCompanionChatRequest(scope = scope),
        )

    suspend fun listChats(limit: Int? = null, before: String? = null): CompanionConversationList {
        val query = buildList<Pair<String, String>> {
            if (limit != null) add("limit" to limit.toString())
            if (before != null) add("before" to before)
        }
        return authorizedRequest(
            method = HttpMethod.Get,
            path = "/api/companion/chats",
            query = query,
        )
    }

    suspend fun getChat(
        chatId: String,
        messagesLimit: Int? = null,
        beforeMessageId: String? = null,
    ): CompanionConversationDetail {
        val query = buildList<Pair<String, String>> {
            if (messagesLimit != null) add("messages_limit" to messagesLimit.toString())
            if (beforeMessageId != null) add("before_message_id" to beforeMessageId)
        }
        return authorizedRequest(
            method = HttpMethod.Get,
            path = "/api/companion/chats/$chatId",
            query = query,
        )
    }

    suspend fun patchChat(
        chatId: String,
        title: String? = null,
        scope: CompanionScope? = null,
        pinned: Boolean? = null,
        archived: Boolean? = null,
    ): CompanionConversation = authorizedRequest(
        method = HttpMethod.Patch,
        path = "/api/companion/chats/$chatId",
        body = PatchCompanionChatRequest(
            title = title,
            scope = scope,
            pinned = pinned,
            archived = archived,
        ),
    )

    suspend fun deleteChat(chatId: String) {
        authorizedRequest<Unit>(
            method = HttpMethod.Delete,
            path = "/api/companion/chats/$chatId",
        )
    }

    /// Open the SSE stream for a new turn and yield typed events.
    fun streamMessage(chatId: String, content: String): Flow<CompanionStreamEvent> = flow {
        val response = transport.streamAuthorized(
            method = HttpMethod.Post,
            path = "/api/companion/chats/$chatId/messages",
            body = PostCompanionMessageRequest(content = content),
            accessTokenProvider = { authStore.currentAccessToken() },
            refresh = { authStore.refresh() },
        )

        val channel = response.bodyAsChannel()
        val buffer = StringBuilder()
        while (true) {
            val line = channel.readUTF8Line() ?: break
            if (line.isEmpty()) {
                val frame = buffer.toString()
                buffer.clear()
                val parsed = parseFrame(frame)
                if (parsed != null) emit(parsed)
                continue
            }
            if (buffer.isNotEmpty()) buffer.append('\n')
            buffer.append(line)
        }
        if (buffer.isNotEmpty()) {
            parseFrame(buffer.toString())?.let { emit(it) }
        }
    }

    private fun parseFrame(frame: String): CompanionStreamEvent? {
        var eventType: String? = null
        var dataLine: String? = null
        for (rawLine in frame.split('\n')) {
            val line = rawLine.trimEnd()
            when {
                line.startsWith("event: ") -> eventType = line.substring("event: ".length).trim()
                line.startsWith("data: ") -> dataLine = line.substring("data: ".length)
            }
        }
        if (eventType == null || dataLine == null) return null
        val data = runCatching { json.parseToJsonElement(dataLine).jsonObject }
            .getOrNull() ?: return null
        return when (eventType) {
            "turn_start" -> CompanionStreamEvent.TurnStart(
                messageId = data.string("message_id"),
                conversationId = data.string("conversation_id"),
            )
            "tool_call" -> CompanionStreamEvent.ToolCall(
                callId = data.string("call_id"),
                tool = data.string("tool"),
            )
            "tool_result" -> CompanionStreamEvent.ToolResult(
                callId = data.string("call_id"),
                summary = data.string("summary"),
            )
            "token" -> CompanionStreamEvent.Token(text = data.string("text"))
            "citation" -> CompanionStreamEvent.Citation(
                index = data.int("index"),
                segmentId = data.string("segment_id"),
                recordingId = data.string("recording_id"),
                startMs = data.intOrNull("start_ms"),
                endMs = data.intOrNull("end_ms"),
                spanStart = data.int("span_start"),
                spanEnd = data.int("span_end"),
            )
            "done" -> CompanionStreamEvent.Done(
                messageId = data.string("message_id"),
                model = data.string("model"),
                latencyMs = data.int("latency_ms"),
            )
            "error" -> CompanionStreamEvent.Error(
                code = data.string("code"),
                message = data.string("message"),
            )
            else -> null
        }
    }

    private suspend inline fun <reified T> authorizedRequest(
        method: HttpMethod,
        path: String,
        query: List<Pair<String, String>> = emptyList(),
        body: Any? = null,
    ): T = transport.authorizedRequest(
        method = method,
        path = path,
        query = query,
        body = body,
        accessTokenProvider = { authStore.currentAccessToken() },
        refresh = { authStore.refresh() },
    )

    companion object {
        internal val defaultJson: Json = Json {
            ignoreUnknownKeys = true
            explicitNulls = false
        }
    }
}

private fun JsonObject.string(key: String): String =
    this[key]?.jsonPrimitive?.contentOrNull ?: ""

private fun JsonObject.int(key: String): Int =
    this[key]?.jsonPrimitive?.intOrNull ?: 0

private fun JsonObject.intOrNull(key: String): Int? =
    this[key]?.jsonPrimitive?.intOrNull
