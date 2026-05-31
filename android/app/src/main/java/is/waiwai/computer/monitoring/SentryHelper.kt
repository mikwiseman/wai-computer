package `is`.waiwai.computer.monitoring

import android.content.Context
import io.sentry.Breadcrumb
import io.sentry.Sentry
import io.sentry.SentryLevel
import io.sentry.android.core.SentryAndroid
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap

object SentryHelper {
    private val lastBreadcrumbAt = ConcurrentHashMap<String, Long>()

    fun start(context: Context, dsn: String) {
        if (dsn.isBlank()) return
        // Android MUST use SentryAndroid.init; the core Sentry.init throws
        // "You are running Android" and crashes Application.onCreate.
        SentryAndroid.init(context) { options ->
            options.dsn = dsn
            options.beforeBreadcrumb = io.sentry.SentryOptions.BeforeBreadcrumbCallback { breadcrumb, _ ->
                sanitizeBreadcrumb(breadcrumb)
            }
            options.beforeSend = io.sentry.SentryOptions.BeforeSendCallback { event, _ ->
                event.user = null
                event.tags?.keys?.toList().orEmpty().forEach { key ->
                    event.setTag(key, sanitizeString(event.tags?.get(key).orEmpty(), key))
                }
                event
            }
        }
    }

    fun setUser(id: String) {
        Sentry.setUser(io.sentry.protocol.User().apply { this.id = id })
    }

    fun clearUser() {
        Sentry.setUser(null)
    }

    fun captureError(t: Throwable, extras: Map<String, Any> = emptyMap()) {
        Sentry.captureException(t) { scope ->
            sanitizeMap(extras).forEach { (key, value) ->
                scope.setExtra(key, value.toString())
            }
        }
    }

    fun addBreadcrumb(
        category: String,
        message: String,
        level: SentryLevel = SentryLevel.INFO,
        data: Map<String, Any> = emptyMap(),
    ) {
        val now = System.currentTimeMillis()
        val previous = lastBreadcrumbAt[category]
        if (previous != null && now - previous < BREADCRUMB_THROTTLE_MS) {
            return
        }
        lastBreadcrumbAt[category] = now
        val breadcrumb = Breadcrumb().apply {
            this.category = category
            this.message = sanitizeString(message, "message")
            this.level = level
            sanitizeMap(data).forEach { (key, value) ->
                setData(key, value)
            }
        }
        Sentry.addBreadcrumb(breadcrumb)
    }

    private fun sanitizeBreadcrumb(breadcrumb: Breadcrumb?): Breadcrumb? {
        breadcrumb ?: return null
        breadcrumb.message = sanitizeString(breadcrumb.message.orEmpty(), "message")
        val data = breadcrumb.data ?: return breadcrumb
        data.keys.toList().forEach { key ->
            breadcrumb.setData(key, sanitizeValue(key, data[key] ?: ""))
        }
        return breadcrumb
    }

    private fun sanitizeMap(values: Map<String, Any>): MutableMap<String, Any> {
        return values.mapValuesTo(mutableMapOf()) { (key, value) ->
            sanitizeValue(key, value)
        }
    }

    private fun sanitizeValue(key: String, value: Any): Any {
        return when (value) {
            is String -> sanitizeString(value, key)
            is ByteArray -> "<bytes:${value.size}>"
            is Map<*, *> -> value.entries.associate { (nestedKey, nestedValue) ->
                nestedKey.toString() to sanitizeValue(nestedKey.toString(), nestedValue ?: "")
            }
            is Iterable<*> -> value.map { sanitizeValue(key, it ?: "") }
            else -> value
        }
    }

    private fun sanitizeString(value: String, key: String): String {
        val normalizedKey = key.lowercase()
        val trimmed = value.trim()
        return when {
            SECRET_KEYS.any(normalizedKey::contains) -> "[REDACTED]"
            EMAIL_KEYS.any(normalizedKey::contains) -> "[REDACTED:${fingerprint(trimmed.lowercase())}]"
            FILE_KEYS.any(normalizedKey::contains) -> "[REDACTED:${fingerprint(trimmed)}]"
            TEXT_KEYS.any(normalizedKey::contains) -> "[REDACTED:${trimmed.length}:${fingerprint(trimmed)}]"
            else -> EMAIL_REGEX.replace(trimmed) { matchResult ->
                "[REDACTED:${fingerprint(matchResult.value.lowercase())}]"
            }
        }
    }

    private fun fingerprint(value: String): String {
        if (value.isEmpty()) return "-"
        return MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray())
            .joinToString("") { byte -> "%02x".format(byte) }
            .take(12)
    }

    private val SECRET_KEYS = listOf("token", "password", "secret", "authorization", "cookie")
    private val EMAIL_KEYS = listOf("email")
    private val FILE_KEYS = listOf("filename", "file_name", "title")
    private val TEXT_KEYS = listOf("transcript", "query", "question", "text", "content", "body", "detail")
    private val EMAIL_REGEX = Regex("[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}", RegexOption.IGNORE_CASE)
    private const val BREADCRUMB_THROTTLE_MS = 5_000L
}
