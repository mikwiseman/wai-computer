package is.waiwai.say.data

import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.android.Android
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.get
import io.ktor.client.request.delete
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.json.Json

class WaiApi(
    private val settingsStore: SettingsStore,
) {
    private val client = HttpClient(Android) {
        install(ContentNegotiation) {
            json(Json {
                ignoreUnknownKeys = true
                explicitNulls = false
            })
        }
    }

    suspend fun sendAgentMessage(message: String, sessionId: String?): AgentChatResponse {
        return client.post(url("/api/agent/chat")) {
            authorized()
            contentType(ContentType.Application.Json)
            setBody(AgentChatRequest(message = message, sessionId = sessionId))
        }.body()
    }

    suspend fun createRealtimeVoiceSession(mode: String): RealtimeVoiceSession {
        return client.post(url("/api/voice/session")) {
            authorized()
            contentType(ContentType.Application.Json)
            setBody(RealtimeVoiceSessionRequest(mode = mode))
        }.body()
    }

    suspend fun listAgents(): List<DigitalAgent> {
        return client.get(url("/api/agents")) {
            authorized()
        }.body()
    }

    suspend fun createAgent(description: String): DigitalAgent {
        return client.post(url("/api/agents")) {
            authorized()
            contentType(ContentType.Application.Json)
            setBody(CreateAgentRequest(description = description))
        }.body()
    }

    suspend fun runAgent(agentId: String) {
        client.post(url("/api/agents/$agentId/run")) {
            authorized()
        }
    }

    suspend fun deleteAgent(agentId: String) {
        client.delete(url("/api/agents/$agentId")) {
            authorized()
        }
    }

    suspend fun listApps(): List<UserApp> {
        return client.get(url("/api/apps")) {
            authorized()
        }.body()
    }

    suspend fun createApp(name: String, description: String?): UserApp {
        return client.post(url("/api/apps")) {
            authorized()
            contentType(ContentType.Application.Json)
            setBody(CreateAppRequest(name = name, displayName = name, description = description))
        }.body()
    }

    suspend fun publishApp(appId: String, visibility: String, appUrl: String?): UserApp {
        return client.post(url("/api/apps/$appId/publish")) {
            authorized()
            contentType(ContentType.Application.Json)
            setBody(PublishAppRequest(visibility = visibility, appUrl = appUrl))
        }.body()
    }

    suspend fun listRecordings(): List<RecordingSummary> {
        return client.get(url("/api/recordings")) {
            authorized()
        }.body()
    }

    private fun url(path: String): String {
        return settingsStore.baseUrl.trimEnd('/') + path
    }

    private fun io.ktor.client.request.HttpRequestBuilder.authorized() {
        val token = settingsStore.accessToken
        if (token.isNotBlank()) {
            header(HttpHeaders.Authorization, "Bearer $token")
        }
    }
}
