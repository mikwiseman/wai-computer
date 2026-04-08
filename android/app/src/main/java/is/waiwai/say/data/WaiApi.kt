package `is`.waiwai.say.data

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

suspend fun askDatabase(question: String, recordingIds: List<String>? = null): QAResponse {
        return client.post(url("/api/qa")) {
            authorized()
            contentType(ContentType.Application.Json)
            setBody(QARequest(question = question, recordingIds = recordingIds))
        }.body()
    }

    suspend fun createRealtimeVoiceSession(mode: String): RealtimeVoiceSession {
        return client.post(url("/api/voice/session")) {
            authorized()
            contentType(ContentType.Application.Json)
            setBody(RealtimeVoiceSessionRequest(mode = mode))
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
