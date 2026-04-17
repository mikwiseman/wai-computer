package `is`.waiwai.say.data

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import `is`.waiwai.say.BuildConfig
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

class SettingsStore(
    private val dataStore: DataStore<Preferences>,
) {
    val settings: Flow<AppSettings> = dataStore.data.map { prefs ->
        AppSettings(
            baseUrl = prefs[Keys.BaseUrl] ?: BuildConfig.DEFAULT_BASE_URL,
            transcriptionLanguage = prefs[Keys.TranscriptionLanguage] ?: DEFAULT_TRANSCRIPTION_LANGUAGE,
            authMode = StoredAuthMode.fromStorage(prefs[Keys.AuthMode]),
            authUserId = prefs[Keys.AuthUserId],
            onboardingSeen = prefs[Keys.OnboardingSeen] == true,
            guestSinceEpochMillis = prefs[Keys.GuestSince],
            legacyAccessToken = prefs[Keys.LegacyAccessToken]?.takeIf { it.isNotBlank() },
        )
    }

    suspend fun snapshot(): AppSettings = settings.first()

    suspend fun updateBaseUrl(baseUrl: String) {
        dataStore.edit { prefs ->
            prefs[Keys.BaseUrl] = baseUrl.trim().ifEmpty { BuildConfig.DEFAULT_BASE_URL }
        }
    }

    suspend fun updateTranscriptionLanguage(language: String) {
        dataStore.edit { prefs ->
            prefs[Keys.TranscriptionLanguage] = language.trim().ifEmpty { DEFAULT_TRANSCRIPTION_LANGUAGE }
        }
    }

    suspend fun setAuthMode(
        mode: StoredAuthMode,
        userId: String? = null,
        guestSinceEpochMillis: Long? = null,
    ) {
        dataStore.edit { prefs ->
            prefs[Keys.AuthMode] = mode.storageValue
            if (userId == null) {
                prefs.remove(Keys.AuthUserId)
            } else {
                prefs[Keys.AuthUserId] = userId
            }
            if (guestSinceEpochMillis == null) {
                prefs.remove(Keys.GuestSince)
            } else {
                prefs[Keys.GuestSince] = guestSinceEpochMillis
            }
        }
    }

    suspend fun markOnboardingSeen() {
        dataStore.edit { prefs ->
            prefs[Keys.OnboardingSeen] = true
        }
    }

    suspend fun resetOnboarding() {
        dataStore.edit { prefs ->
            prefs[Keys.OnboardingSeen] = false
        }
    }

    suspend fun setLegacyAccessToken(token: String?) {
        dataStore.edit { prefs ->
            val normalized = token?.trim().orEmpty()
            if (normalized.isEmpty()) {
                prefs.remove(Keys.LegacyAccessToken)
            } else {
                prefs[Keys.LegacyAccessToken] = normalized
            }
        }
    }

    suspend fun clearLegacyAccessToken() {
        dataStore.edit { prefs ->
            prefs.remove(Keys.LegacyAccessToken)
        }
    }

    private object Keys {
        val BaseUrl = stringPreferencesKey("base_url")
        val TranscriptionLanguage = stringPreferencesKey("transcription_language")
        val AuthMode = stringPreferencesKey("auth_mode")
        val AuthUserId = stringPreferencesKey("auth_user_id")
        val OnboardingSeen = androidx.datastore.preferences.core.booleanPreferencesKey("onboarding_seen")
        val GuestSince = longPreferencesKey("guest_since_epoch_millis")
        val LegacyAccessToken = stringPreferencesKey("legacy_access_token")
    }

    companion object {
        const val DEFAULT_TRANSCRIPTION_LANGUAGE = "multi"
    }
}

data class AppSettings(
    val baseUrl: String,
    val transcriptionLanguage: String,
    val authMode: StoredAuthMode,
    val authUserId: String?,
    val onboardingSeen: Boolean,
    val guestSinceEpochMillis: Long?,
    val legacyAccessToken: String?,
)

enum class StoredAuthMode(val storageValue: String) {
    Onboarding("onboarding"),
    Guest("guest"),
    Authenticated("authenticated");

    companion object {
        fun fromStorage(value: String?): StoredAuthMode {
            return entries.firstOrNull { it.storageValue == value } ?: Onboarding
        }
    }
}
