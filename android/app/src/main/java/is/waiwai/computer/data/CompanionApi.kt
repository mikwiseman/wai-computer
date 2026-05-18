package `is`.waiwai.computer.data

import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.HttpMethod
import io.ktor.utils.io.readUTF8Line
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.Dispatchers
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
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

    /// Open the SSE stream for a new turn and yield typed events. Cancelling
    /// the consuming collector cancels the underlying HTTP call.
    fun streamMessage(chatId: String, content: String): Flow<CompanionStreamEvent> = flow {
        val response = transport.streamAuthorized(
            method = HttpMethod.Post,
            path = "/api/companion/chats/$chatId/messages",
            body = PostCompanionMessageRequest(content = content),
            accessTokenProvider = { authStore.currentAccessToken() },
            refresh = { authStore.refresh() },
        )

        try {
            val channel = response.bodyAsChannel()
            val dataLines = mutableListOf<String>()
            var eventType: String? = null
            var sawContentLine = false
            while (true) {
                val rawLine = channel.readUTF8Line() ?: break
                val line = rawLine.trimEnd('\r')
                if (line.isEmpty()) {
                    if (sawContentLine) {
                        parseFrame(eventType, dataLines)?.let { emit(it) }
                    }
                    dataLines.clear()
                    eventType = null
                    sawContentLine = false
                    continue
                }
                if (line.startsWith(":")) {
                    // SSE comment / heartbeat — skip without resetting state.
                    continue
                }
                sawContentLine = true
                when {
                    line.startsWith("event:") -> {
                        eventType = stripOptionalLeadingSpace(line.substring("event:".length)).trim()
                    }
                    line.startsWith("data:") -> {
                        dataLines.add(stripOptionalLeadingSpace(line.substring("data:".length)))
                    }
                    line.startsWith("id:") || line.startsWith("retry:") -> {
                        // Recognized but unused fields.
                    }
                    else -> {
                        emit(
                            CompanionStreamEvent.Error(
                                code = "parse_error",
                                message = "Unrecognized SSE line: $line",
                            ),
                        )
                    }
                }
            }
            // Flush any final unterminated frame.
            if (sawContentLine) {
                parseFrame(eventType, dataLines)?.let { emit(it) }
            }
        } catch (cancel: CancellationException) {
            throw cancel
        } finally {
            // Always tear down the underlying HTTP call so cancellation closes
            // the socket and doesn't keep counting tokens on the server. The
            // response coroutine context owns the connection lifetime.
            runCatching { response.cancel() }
        }
    }.flowOn(Dispatchers.IO)

    private fun parseFrame(
        eventType: String?,
        dataLines: List<String>,
    ): CompanionStreamEvent? {
        if (eventType == null) {
            return CompanionStreamEvent.Error(
                code = "parse_error",
                message = "SSE frame missing event: field",
            )
        }
        if (dataLines.isEmpty()) {
            return CompanionStreamEvent.Error(
                code = "parse_error",
                message = "SSE frame for '$eventType' has no data: line",
            )
        }
        val payload = dataLines.joinToString(separator = "\n")
        val data = runCatching { json.parseToJsonElement(payload).jsonObject }
            .getOrElse { error ->
                return CompanionStreamEvent.Error(
                    code = "parse_error",
                    message = "Invalid JSON in '$eventType' frame: ${error.message}",
                )
            }
        return try {
            when (eventType) {
                "turn_start" -> CompanionStreamEvent.TurnStart(
                    messageId = data.requiredString("message_id"),
                    conversationId = data.requiredString("conversation_id"),
                )
                "tool_call" -> CompanionStreamEvent.ToolCall(
                    callId = data.requiredString("call_id"),
                    tool = data.requiredString("tool"),
                )
                "tool_result" -> CompanionStreamEvent.ToolResult(
                    callId = data.requiredString("call_id"),
                    summary = data.requiredString("summary"),
                )
                "token" -> CompanionStreamEvent.Token(text = data.requiredString("text"))
                "citation" -> CompanionStreamEvent.Citation(
                    index = data.requiredInt("index"),
                    segmentId = data.requiredString("segment_id"),
                    recordingId = data.requiredString("recording_id"),
                    startMs = data.optionalInt("start_ms"),
                    endMs = data.optionalInt("end_ms"),
                    spanStart = data.requiredInt("span_start"),
                    spanEnd = data.requiredInt("span_end"),
                )
                "done" -> CompanionStreamEvent.Done(
                    messageId = data.requiredString("message_id"),
                    model = data.requiredString("model"),
                    latencyMs = data.requiredInt("latency_ms"),
                )
                "error" -> CompanionStreamEvent.Error(
                    code = data.requiredString("code"),
                    message = data.requiredString("message"),
                )
                else -> CompanionStreamEvent.Error(
                    code = "parse_error",
                    message = "Unknown SSE event type: $eventType",
                )
            }
        } catch (err: IllegalStateException) {
            CompanionStreamEvent.Error(
                code = "parse_error",
                message = err.message ?: "Missing field in '$eventType' frame",
            )
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

private fun stripOptionalLeadingSpace(value: String): String =
    if (value.startsWith(" ")) value.substring(1) else value

private fun JsonObject.requiredString(key: String): String =
    this[key]?.jsonPrimitive?.contentOrNull
        ?: error("Required field '$key' missing")

private fun JsonObject.requiredInt(key: String): Int =
    this[key]?.jsonPrimitive?.intOrNull
        ?: error("Required field '$key' missing or not an int")

private fun JsonObject.optionalInt(key: String): Int? =
    this[key]?.jsonPrimitive?.intOrNull
