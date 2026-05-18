package `is`.waiwai.computer.data

import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.android.Android
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.HttpRequestBuilder
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.patch
import io.ktor.client.request.post
import io.ktor.client.request.prepareGet
import io.ktor.client.request.preparePatch
import io.ktor.client.request.preparePost
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.URLBuilder
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import io.ktor.utils.io.errors.IOException
import `is`.waiwai.computer.monitoring.SentryHelper
import java.io.File
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

class WaiApi(
    private val transport: ApiTransport,
    private val authStore: AuthStoreContract,
) {
    suspend fun me(): UserSummary = authorizedRequest(HttpMethod.Get, "/api/auth/me")

    suspend fun listRecordings(limit: Int = 50): List<Recording> = authorizedRequest(
        method = HttpMethod.Get,
        path = "/api/recordings",
        query = listOf("limit" to limit.toString()),
    )

    suspend fun listFolders(): List<Folder> = authorizedRequest(HttpMethod.Get, "/api/folders")

    suspend fun createRecording(
        title: String? = null,
        type: RecordingType,
        language: String,
        folderId: String? = null,
    ): Recording = authorizedRequest(
        method = HttpMethod.Post,
        path = "/api/recordings",
        body = CreateRecordingRequest(
            title = title,
            type = type,
            language = language,
            folderId = folderId,
        ),
    )

    suspend fun getRecording(id: String): RecordingDetail =
        authorizedRequest(HttpMethod.Get, "/api/recordings/$id")

    suspend fun updateRecordingTitle(id: String, title: String?): Recording =
        authorizedRequest(
            method = HttpMethod.Patch,
            path = "/api/recordings/$id",
            body = UpdateRecordingRequest(title = title),
        )

    suspend fun moveRecording(id: String, folderId: String?): Recording =
        authorizedRequest(
            method = HttpMethod.Patch,
            path = "/api/recordings/$id",
            body = UpdateRecordingRequest(folderId = folderId),
        )

    suspend fun deleteRecording(id: String, permanent: Boolean = false) {
        authorizedRequest<Unit>(
            method = HttpMethod.Delete,
            path = "/api/recordings/$id",
            query = if (permanent) listOf("permanent" to "true") else emptyList(),
        )
    }

    suspend fun updateActionItem(id: String, status: ActionItemStatus): ActionItem =
        authorizedRequest(
            method = HttpMethod.Patch,
            path = "/api/action-items/$id",
            body = UpdateActionItemRequest(status = status),
        )

    suspend fun getSettings(): UserSettings = authorizedRequest(
        method = HttpMethod.Get,
        path = "/api/settings",
    )

    suspend fun getTranscriptionOptions(): TranscriptionOptions = authorizedRequest(
        method = HttpMethod.Get,
        path = "/api/settings/transcription-options",
    )

    suspend fun updateSettings(request: UpdateSettingsRequest): UserSettings = authorizedRequest(
        method = HttpMethod.Patch,
        path = "/api/settings",
        body = request,
    )

    suspend fun createRealtimeTranscriptionSession(
        language: String,
        channels: Int = 1,
    ): RealtimeTranscriptionSessionConfig = authorizedRequest(
        method = HttpMethod.Post,
        path = "/api/transcription/session",
        body = CreateRealtimeTranscriptionSessionRequest(language = language, channels = channels),
    )

    suspend fun saveLiveTranscript(
        recordingId: String,
        segments: List<LiveTranscriptSegment>,
        durationSeconds: Int,
    ): RecordingDetail = authorizedRequest(
        method = HttpMethod.Post,
        path = "/api/recordings/$recordingId/transcript",
        body = SaveTranscriptRequest(
            segments = segments.map {
                TranscriptSegmentPayload(
                    text = it.text,
                    speaker = it.speaker,
                    startMs = it.startMs,
                    endMs = it.endMs,
                    confidence = it.confidence,
                )
            },
            durationSeconds = durationSeconds,
        ),
    )

    suspend fun listPeople(): List<Person> =
        authorizedRequest(HttpMethod.Get, "/api/people")

    suspend fun createPerson(displayName: String, color: String? = null): Person =
        authorizedRequest(
            method = HttpMethod.Post,
            path = "/api/people",
            body = CreatePersonRequest(displayName = displayName, color = color),
        )

    suspend fun assignSpeaker(
        recordingId: String,
        rawLabel: String,
        personId: String? = null,
        newDisplayName: String? = null,
    ): RecordingDetail = authorizedRequest(
        method = HttpMethod.Post,
        path = "/api/recordings/$recordingId/assign-speaker",
        body = AssignSpeakerRequest(
            rawLabel = rawLabel,
            personId = personId,
            newDisplayName = newDisplayName,
        ),
    )

    suspend fun uploadAudio(recordingId: String, file: File): RecordingDetail {
        return transport.authorizedUpload(
            path = "/api/recordings/$recordingId/upload",
            file = file,
            accessTokenProvider = { authStore.currentAccessToken() },
            refresh = { authStore.refresh() },
        )
    }

    private suspend inline fun <reified T> authorizedRequest(
        method: HttpMethod,
        path: String,
        query: List<Pair<String, String>> = emptyList(),
        body: Any? = null,
    ): T {
        return transport.authorizedRequest(
            method = method,
            path = path,
            query = query,
            body = body,
            accessTokenProvider = { authStore.currentAccessToken() },
            refresh = { authStore.refresh() },
        )
    }
}

interface AuthStoreContract {
    suspend fun currentAccessToken(): String?
    suspend fun refresh(): Boolean
}

class ApiTransport(
    private val settingsStore: SettingsStore,
    private val client: HttpClient = defaultHttpClient(),
) {
    internal suspend inline fun <reified T> request(
        method: HttpMethod,
        path: String,
        query: List<Pair<String, String>> = emptyList(),
        body: Any? = null,
        bearerToken: String? = null,
    ): T {
        val response = execute(
            method = method,
            path = path,
            query = query,
            body = body,
            bearerToken = bearerToken,
        )
        return decode(response)
    }

    internal suspend inline fun <reified T> authorizedRequest(
        method: HttpMethod,
        path: String,
        query: List<Pair<String, String>> = emptyList(),
        body: Any? = null,
        accessTokenProvider: suspend () -> String?,
        refresh: suspend () -> Boolean,
    ): T {
        val accessToken = accessTokenProvider()
        val first = execute(method, path, query, body, accessToken)
        if (first.status.value != 401) {
            return decode(first)
        }
        if (!refresh()) {
            throw ApiError.Unauthorized
        }
        val second = execute(method, path, query, body, accessTokenProvider())
        if (second.status.value == 401) {
            throw ApiError.Unauthorized
        }
        return decode(second)
    }

    internal suspend inline fun <reified T> authorizedUpload(
        path: String,
        file: File,
        accessTokenProvider: suspend () -> String?,
        refresh: suspend () -> Boolean,
    ): T {
        val first = upload(path, file, accessTokenProvider())
        if (first.status.value != 401) {
            return decode(first)
        }
        if (!refresh()) {
            throw ApiError.Unauthorized
        }
        val second = upload(path, file, accessTokenProvider())
        if (second.status.value == 401) {
            throw ApiError.Unauthorized
        }
        return decode(second)
    }

    suspend fun execute(
        method: HttpMethod,
        path: String,
        query: List<Pair<String, String>> = emptyList(),
        body: Any? = null,
        bearerToken: String? = null,
    ): HttpResponse {
        val url = resolveUrl(path, query)
        SentryHelper.addBreadcrumb(
            category = "http.request",
            message = "${method.value} $path",
            data = mapOf("path" to path, "method" to method.value),
        )
        return try {
            client.request(url) {
                this.method = method
                applyCommonHeaders(bearerToken)
                if (body != null) {
                    contentType(ContentType.Application.Json)
                    setBody(body)
                }
            }.also { response ->
                SentryHelper.addBreadcrumb(
                    category = "http.response",
                    message = "${response.status.value} $path",
                    data = mapOf("path" to path, "status" to response.status.value),
                )
            }
        } catch (error: SerializationException) {
            throw ApiError.Serialization(error)
        } catch (error: IOException) {
            SentryHelper.captureError(error, mapOf("path" to path, "method" to method.value))
            throw ApiError.Network(error)
        } catch (error: Throwable) {
            SentryHelper.captureError(error, mapOf("path" to path, "method" to method.value))
            throw ApiError.Network(error)
        }
    }

    suspend fun upload(
        path: String,
        file: File,
        bearerToken: String?,
    ): HttpResponse {
        val boundary = "WaiComputer-${System.currentTimeMillis()}"
        val fileBytes = file.readBytes()
        val mimeType = when (file.extension.lowercase()) {
            "wav" -> "audio/wav"
            "mp3" -> "audio/mpeg"
            "m4a" -> "audio/mp4"
            else -> "application/octet-stream"
        }
        val bodyBytes = buildMultipartBody(boundary, file.name, mimeType, fileBytes)
        val url = resolveUrl(path, emptyList())
        SentryHelper.addBreadcrumb(
            category = "http.upload",
            message = "POST $path",
            data = mapOf("path" to path, "extension" to file.extension.lowercase()),
        )
        return try {
            client.request(url) {
                method = HttpMethod.Post
                applyCommonHeaders(bearerToken)
                header(HttpHeaders.ContentType, "multipart/form-data; boundary=$boundary")
                setBody(bodyBytes)
            }.also { response ->
                SentryHelper.addBreadcrumb(
                    category = "http.upload.response",
                    message = "${response.status.value} $path",
                    data = mapOf("path" to path, "status" to response.status.value),
                )
            }
        } catch (error: IOException) {
            SentryHelper.captureError(error, mapOf("path" to path))
            throw ApiError.Network(error)
        } catch (error: Throwable) {
            SentryHelper.captureError(error, mapOf("path" to path))
            throw ApiError.Network(error)
        }
    }

    suspend fun close() {
        client.close()
    }

    /// Execute a streaming request with bearer-token refresh-on-401. Throws
    /// `ApiError.Http` (or `Unauthorized`) on non-2xx so the caller never
    /// iterates a JSON error body as an event stream.
    suspend fun streamAuthorized(
        method: HttpMethod,
        path: String,
        body: Any? = null,
        query: List<Pair<String, String>> = emptyList(),
        accessTokenProvider: suspend () -> String?,
        refresh: suspend () -> Boolean,
    ): HttpResponse {
        val first = streamRequest(method, path, query, body, accessTokenProvider())
        if (first.status.value == 401) {
            runCatching { first.bodyAsText() }
            if (!refresh()) {
                throw ApiError.Unauthorized
            }
            val second = streamRequest(method, path, query, body, accessTokenProvider())
            if (second.status.value == 401) {
                throw ApiError.Unauthorized
            }
            return ensureSuccessOrThrow(second, path)
        }
        return ensureSuccessOrThrow(first, path)
    }

    private suspend fun ensureSuccessOrThrow(
        response: HttpResponse,
        path: String,
    ): HttpResponse {
        if (response.status.value in 200..299) {
            return response
        }
        SentryHelper.addBreadcrumb(
            category = "http.stream",
            message = "${response.status.value} $path",
            data = mapOf("path" to path, "status" to response.status.value),
        )
        val detail = runCatching { response.bodyAsText() }
            .getOrNull()
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
        throw ApiError.Http(response.status.value, detail)
    }

    private suspend fun streamRequest(
        method: HttpMethod,
        path: String,
        query: List<Pair<String, String>>,
        body: Any?,
        bearerToken: String?,
    ): HttpResponse {
        val url = resolveUrl(path, query)
        return client.request(url) {
            this.method = method
            applyCommonHeaders(bearerToken, accept = "text/event-stream")
            header(HttpHeaders.CacheControl, "no-cache")
            if (body != null) {
                contentType(ContentType.Application.Json)
                setBody(body)
            }
        }
    }

    private fun HttpRequestBuilder.applyCommonHeaders(
        bearerToken: String?,
        accept: String = ContentType.Application.Json.toString(),
    ) {
        if (!bearerToken.isNullOrBlank()) {
            header(HttpHeaders.Authorization, "Bearer $bearerToken")
        }
        headers.remove(HttpHeaders.Accept)
        header(HttpHeaders.Accept, accept)
    }

    private suspend fun resolveUrl(path: String, query: List<Pair<String, String>>): String {
        val baseUrl = settingsStore.snapshot().baseUrl.trimEnd('/')
        val builder = URLBuilder("$baseUrl$path")
        query.forEach { (key, value) ->
            builder.parameters.append(key, value)
        }
        return builder.buildString()
    }

    private suspend inline fun <reified T> decode(response: HttpResponse): T {
        if (response.status.value in 200..299) {
            if (T::class == Unit::class) {
                @Suppress("UNCHECKED_CAST")
                return Unit as T
            }
            return try {
                response.body()
            } catch (error: SerializationException) {
                throw ApiError.Serialization(error)
            }
        }

        if (response.status.value == 401) {
            throw ApiError.Unauthorized
        }

        val detail = response.bodyAsText().trim().takeIf { it.isNotEmpty() }
        throw ApiError.Http(response.status.value, detail)
    }

    private fun buildMultipartBody(
        boundary: String,
        fileName: String,
        mimeType: String,
        content: ByteArray,
    ): ByteArray {
        val lineBreak = "\r\n"
        val header = buildString {
            append("--").append(boundary).append(lineBreak)
            append("Content-Disposition: form-data; name=\"file\"; filename=\"")
            append(fileName)
            append('"').append(lineBreak)
            append("Content-Type: ").append(mimeType).append(lineBreak)
            append(lineBreak)
        }.toByteArray()
        val footer = "$lineBreak--$boundary--$lineBreak".toByteArray()
        return ByteArray(header.size + content.size + footer.size).also { bytes ->
            System.arraycopy(header, 0, bytes, 0, header.size)
            System.arraycopy(content, 0, bytes, header.size, content.size)
            System.arraycopy(footer, 0, bytes, header.size + content.size, footer.size)
        }
    }

    private companion object {
        fun defaultHttpClient(): HttpClient {
            return HttpClient(Android) {
                install(ContentNegotiation) {
                    json(
                        Json {
                            ignoreUnknownKeys = true
                            explicitNulls = false
                            isLenient = true
                        },
                    )
                }
            }
        }
    }
}
