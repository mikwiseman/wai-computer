package `is`.waiwai.say.settings

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import `is`.waiwai.say.BuildConfig
import `is`.waiwai.say.R
import `is`.waiwai.say.auth.AuthState
import `is`.waiwai.say.auth.AuthViewModel
import `is`.waiwai.say.data.AppContainer
import `is`.waiwai.say.data.TranscriptionModelOption
import `is`.waiwai.say.data.TranscriptionOptions
import `is`.waiwai.say.data.UpdateSettingsRequest
import `is`.waiwai.say.data.UserSettings
import `is`.waiwai.say.ui.TestTags
import kotlinx.coroutines.launch

private data class StorageSummary(
    val count: Int = 0,
    val sizeMb: Double = 0.0,
)

private enum class ModelPreference {
    DictationLive,
    RecordingLive,
    File,
    DictationPostFilter,
}

private const val STABLE_TRANSCRIPTION_MODELS_LOCKED = true
private const val STABLE_DICTATION_PROVIDER = "elevenlabs"
private const val STABLE_DICTATION_MODEL = "scribe_v2_realtime"
private const val STABLE_RECORDING_PROVIDER = "elevenlabs"
private const val STABLE_RECORDING_MODEL = "scribe_v2_realtime"
private const val STABLE_FILE_PROVIDER = "elevenlabs"
private const val STABLE_FILE_MODEL = "scribe_v2"
private const val STABLE_POST_FILTER_PROVIDER = "anthropic"
private const val STABLE_POST_FILTER_MODEL = "claude-haiku-4-5"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    modifier: Modifier = Modifier,
    container: AppContainer,
    isGuest: Boolean,
    onContinueSignIn: () -> Unit,
    authViewModel: AuthViewModel,
) {
    val settings by container.settingsStore.settings.collectAsStateWithLifecycle(
        initialValue = `is`.waiwai.say.data.AppSettings(
            baseUrl = BuildConfig.DEFAULT_BASE_URL,
            transcriptionLanguage = `is`.waiwai.say.data.SettingsStore.DEFAULT_TRANSCRIPTION_LANGUAGE,
            authMode = `is`.waiwai.say.data.StoredAuthMode.Onboarding,
            authUserId = null,
            onboardingSeen = false,
            guestSinceEpochMillis = null,
            legacyAccessToken = null,
        ),
    )
    val authState by container.authStore.state.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var storageRefreshKey by rememberSaveable { mutableIntStateOf(0) }
    var showLanguageSheet by rememberSaveable { mutableStateOf(false) }
    var activeModelPreference by remember { mutableStateOf<ModelPreference?>(null) }
    var accountSettings by remember { mutableStateOf<UserSettings?>(null) }
    var transcriptionOptions by remember { mutableStateOf<TranscriptionOptions?>(null) }
    var settingsError by remember { mutableStateOf<String?>(null) }
    var showClearCacheConfirm by rememberSaveable { mutableStateOf(false) }
    var showDeleteAccountConfirm by rememberSaveable { mutableStateOf(false) }
    var draftBaseUrl by rememberSaveable(settings.baseUrl) { mutableStateOf(settings.baseUrl) }
    var draftAccessToken by rememberSaveable(settings.legacyAccessToken) { mutableStateOf(settings.legacyAccessToken.orEmpty()) }
    val storageSummary by produceState(initialValue = StorageSummary(), container, storageRefreshKey) {
        value = StorageSummary(
            count = container.localRecordingStore.listPending().size,
            sizeMb = container.localRecordingStore.totalUsageBytes() / (1024.0 * 1024.0),
        )
    }

    val languageOptions = remember {
        listOf("multi", "en", "ru", "es", "fr", "de", "ja", "ko", "zh")
    }

    fun saveAccountSettings(request: UpdateSettingsRequest) {
        scope.launch {
            try {
                accountSettings = container.waiApi.updateSettings(request)
                settingsError = null
            } catch (error: Throwable) {
                settingsError = error.localizedMessage ?: "Couldn't save account settings."
            }
        }
    }

    LaunchedEffect(authState) {
        if (authState is AuthState.Authenticated) {
            transcriptionOptions = null
            try {
                accountSettings = container.waiApi.getSettings()
                if (
                    STABLE_TRANSCRIPTION_MODELS_LOCKED &&
                    accountSettings?.requiresStableTranscriptionReset() == true
                ) {
                    accountSettings = container.waiApi.updateSettings(stableTranscriptionUpdateRequest())
                }
                settingsError = null
            } catch (error: Throwable) {
                settingsError = error.localizedMessage ?: "Couldn't load account settings."
                transcriptionOptions = null
                return@LaunchedEffect
            }

            if (STABLE_TRANSCRIPTION_MODELS_LOCKED) {
                transcriptionOptions = null
                return@LaunchedEffect
            }

            try {
                transcriptionOptions = container.waiApi.getTranscriptionOptions()
                settingsError = null
            } catch (error: Throwable) {
                settingsError = error.localizedMessage ?: "Couldn't load transcription model options."
                transcriptionOptions = null
            }
        } else {
            accountSettings = null
            transcriptionOptions = null
            settingsError = null
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 24.dp)
            .verticalScroll(rememberScrollState())
            .widthIn(max = 560.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            text = stringResource(R.string.tab_settings),
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(top = 24.dp),
        )

        SettingsSectionCard(title = stringResource(R.string.settings_account)) {
            when (val state = authState) {
                is AuthState.Authenticated -> {
                    Text(stringResource(R.string.settings_signed_in_as, state.user.email))
                    Button(onClick = authViewModel::logout, modifier = Modifier.fillMaxWidth()) {
                        Text(stringResource(R.string.settings_sign_out))
                    }
                    // In-app account deletion (App Store 5.1.1(v) / Play Data Safety).
                    TextButton(
                        onClick = { showDeleteAccountConfirm = true },
                        modifier = Modifier.testTag(TestTags.SettingsDeleteAccountButton),
                    ) {
                        Text(
                            text = stringResource(R.string.settings_delete_account),
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                    Text(
                        text = stringResource(R.string.settings_delete_account_footer),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                is AuthState.Guest,
                AuthState.Onboarding,
                AuthState.Unknown,
                is AuthState.SessionExpired,
                -> {
                    Text(stringResource(R.string.settings_sign_in_sync))
                    Button(
                        onClick = onContinueSignIn,
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag(TestTags.SettingsSignInButton),
                    ) {
                        Text(stringResource(R.string.guest_banner_sign_in_to_sync))
                    }
                }
            }
        }

        SettingsSectionCard(title = stringResource(R.string.settings_transcription)) {
            TextButton(onClick = { showLanguageSheet = true }) {
                Text(languageLabel(settings.transcriptionLanguage))
            }

            when {
                authState !is AuthState.Authenticated -> {
                    Text(
                        text = stringResource(R.string.settings_sign_in_sync),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                accountSettings != null && (STABLE_TRANSCRIPTION_MODELS_LOCKED || transcriptionOptions != null) -> {
                    val currentSettings = accountSettings!!
                    val options = transcriptionOptions
                    if (STABLE_TRANSCRIPTION_MODELS_LOCKED) {
                        LockedModelRow(
                            title = stringResource(R.string.settings_dictation_live_model),
                            value = "ElevenLabs Scribe v2 Realtime",
                        )
                        LockedModelRow(
                            title = stringResource(R.string.settings_recording_live_model),
                            value = "ElevenLabs Scribe v2 Realtime",
                        )
                        LockedModelRow(
                            title = stringResource(R.string.settings_file_model),
                            value = "ElevenLabs Scribe v2",
                        )
                    } else if (options != null) {
                        ModelChoiceRow(
                            title = stringResource(R.string.settings_dictation_live_model),
                            value = optionLabel(
                                options.dictationLiveStt,
                                currentSettings.dictationLiveSttProvider,
                                currentSettings.dictationLiveSttModel,
                            ),
                            onClick = { activeModelPreference = ModelPreference.DictationLive },
                        )
                        ModelChoiceRow(
                            title = stringResource(R.string.settings_recording_live_model),
                            value = optionLabel(
                                options.recordingLiveStt,
                                currentSettings.recordingLiveSttProvider,
                                currentSettings.recordingLiveSttModel,
                            ),
                            onClick = { activeModelPreference = ModelPreference.RecordingLive },
                        )
                        ModelChoiceRow(
                            title = stringResource(R.string.settings_file_model),
                            value = optionLabel(
                                options.fileStt,
                                currentSettings.fileSttProvider,
                                currentSettings.fileSttModel,
                            ),
                            onClick = { activeModelPreference = ModelPreference.File },
                        )
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = stringResource(R.string.settings_dictation_post_filter),
                            modifier = Modifier.weight(1f),
                        )
                        Switch(
                            checked = if (STABLE_TRANSCRIPTION_MODELS_LOCKED) {
                                true
                            } else {
                                currentSettings.dictationPostFilterEnabled
                            },
                            onCheckedChange = if (STABLE_TRANSCRIPTION_MODELS_LOCKED) {
                                null
                            } else {
                                { enabled ->
                                    saveAccountSettings(
                                        UpdateSettingsRequest(dictationPostFilterEnabled = enabled),
                                    )
                                }
                            },
                        )
                    }
                    if (STABLE_TRANSCRIPTION_MODELS_LOCKED) {
                        LockedModelRow(
                            title = stringResource(R.string.settings_dictation_post_filter_model),
                            value = "Claude Haiku 4.5",
                        )
                    } else if (currentSettings.dictationPostFilterEnabled && options != null) {
                        ModelChoiceRow(
                            title = stringResource(R.string.settings_dictation_post_filter_model),
                            value = optionLabel(
                                options.dictationPostFilter,
                                currentSettings.dictationPostFilterProvider,
                                currentSettings.dictationPostFilterModel,
                            ),
                            onClick = { activeModelPreference = ModelPreference.DictationPostFilter },
                        )
                    }
                    if (settingsError != null) {
                        Text(
                            text = settingsError.orEmpty(),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
                settingsError != null -> {
                    Text(
                        text = settingsError.orEmpty(),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
                else -> {
                    Text(
                        text = stringResource(R.string.settings_loading_account_models),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        SettingsSectionCard(title = stringResource(R.string.settings_storage)) {
            Text(stringResource(R.string.settings_storage_count, storageSummary.count))
            Text(stringResource(R.string.settings_storage_size, storageSummary.sizeMb))
            Button(onClick = { showClearCacheConfirm = true }) {
                Text(stringResource(R.string.settings_storage_clear))
            }
        }

        SettingsSectionCard(title = stringResource(R.string.settings_about)) {
            Text("${stringResource(R.string.settings_about_version)}: ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
            TextButton(
                onClick = {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://waiwai.is/say/privacy")))
                },
            ) {
                Text(stringResource(R.string.settings_about_privacy))
            }
            TextButton(
                onClick = {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://waiwai.is/say/terms")))
                },
            ) {
                Text(stringResource(R.string.settings_about_terms))
            }
            TextButton(
                onClick = {
                    context.startActivity(
                        Intent(
                            Intent.ACTION_SENDTO,
                            Uri.parse(
                                "mailto:support@waiwai.is?subject=WaiSay%20Android%20v${BuildConfig.VERSION_NAME}",
                            ),
                        ),
                    )
                },
            ) {
                Text(stringResource(R.string.settings_about_feedback))
            }
        }

        if (BuildConfig.DEBUG) {
            SettingsSectionCard(title = stringResource(R.string.settings_developer)) {
                OutlinedTextField(
                    value = draftBaseUrl,
                    onValueChange = { draftBaseUrl = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.settings_base_url)) },
                )
                Button(
                    onClick = {
                        scope.launch {
                            container.settingsStore.updateBaseUrl(draftBaseUrl)
                        }
                    },
                ) {
                    Text(stringResource(R.string.settings_save_base_url))
                }
                OutlinedTextField(
                    value = draftAccessToken,
                    onValueChange = { draftAccessToken = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.settings_access_token)) },
                )
                Button(
                    onClick = {
                        scope.launch {
                            container.settingsStore.setLegacyAccessToken(draftAccessToken)
                        }
                    },
                ) {
                    Text(stringResource(R.string.settings_save_access_token))
                }
                TextButton(
                    onClick = {
                        scope.launch {
                            container.settingsStore.resetOnboarding()
                        }
                    },
                ) {
                    Text(stringResource(R.string.settings_reset_onboarding))
                }
            }
        }
    }

    if (showLanguageSheet) {
        ModalBottomSheet(
            onDismissRequest = { showLanguageSheet = false },
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 24.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    text = stringResource(R.string.settings_language_sheet_title),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                languageOptions.forEach { code ->
                    TextButton(
                        onClick = {
                            scope.launch {
                                container.settingsStore.updateTranscriptionLanguage(code)
                                showLanguageSheet = false
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(languageLabel(code))
                    }
                }
            }
        }
    }

    if (
        !STABLE_TRANSCRIPTION_MODELS_LOCKED &&
        activeModelPreference != null &&
        accountSettings != null &&
        transcriptionOptions != null
    ) {
        val preference = activeModelPreference!!
        val options = modelOptionsFor(preference, transcriptionOptions!!)
        val title = when (preference) {
            ModelPreference.DictationLive -> stringResource(R.string.settings_dictation_live_model)
            ModelPreference.RecordingLive -> stringResource(R.string.settings_recording_live_model)
            ModelPreference.File -> stringResource(R.string.settings_file_model)
            ModelPreference.DictationPostFilter -> stringResource(R.string.settings_dictation_post_filter_model)
        }

        ModalBottomSheet(
            onDismissRequest = { activeModelPreference = null },
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 24.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                options.forEach { option ->
                    TextButton(
                        onClick = {
                            saveAccountSettings(updateRequestFor(preference, option))
                            activeModelPreference = null
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.fillMaxWidth()) {
                            Text(option.label)
                            Text(
                                text = option.description,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }
    }

    if (showDeleteAccountConfirm) {
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { showDeleteAccountConfirm = false },
            title = { Text(stringResource(R.string.settings_delete_account_title)) },
            text = { Text(stringResource(R.string.settings_delete_account_message)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showDeleteAccountConfirm = false
                        authViewModel.deleteAccount()
                    },
                ) {
                    Text(
                        text = stringResource(R.string.settings_delete_account_confirm),
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteAccountConfirm = false }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }

    if (showClearCacheConfirm) {
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { showClearCacheConfirm = false },
            title = { Text(stringResource(R.string.settings_storage_clear)) },
            text = { Text(stringResource(R.string.settings_storage_clear_confirm)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        scope.launch {
                            container.localRecordingStore.clearAll()
                            storageRefreshKey += 1
                            showClearCacheConfirm = false
                        }
                    },
                ) {
                    Text(stringResource(R.string.common_done))
                }
            },
            dismissButton = {
                TextButton(onClick = { showClearCacheConfirm = false }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }
}

@Composable
private fun SettingsSectionCard(
    title: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            content = {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                content()
            },
        )
    }
}

@Composable
private fun LockedModelRow(
    title: String,
    value: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(title)
            Text(
                text = value,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ModelChoiceRow(
    title: String,
    value: String,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(title)
            Text(
                text = value,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(modifier = Modifier.width(12.dp))
        TextButton(onClick = onClick) {
            Text(stringResource(R.string.common_change))
        }
    }
}

private fun optionLabel(
    options: List<TranscriptionModelOption>,
    provider: String,
    model: String,
): String {
    return options.firstOrNull { it.provider == provider && it.model == model }?.label ?: "$provider / $model"
}

private fun modelOptionsFor(
    preference: ModelPreference,
    options: TranscriptionOptions,
): List<TranscriptionModelOption> = when (preference) {
    ModelPreference.DictationLive -> options.dictationLiveStt
    ModelPreference.RecordingLive -> options.recordingLiveStt
    ModelPreference.File -> options.fileStt
    ModelPreference.DictationPostFilter -> options.dictationPostFilter
}

private fun updateRequestFor(
    preference: ModelPreference,
    option: TranscriptionModelOption,
): UpdateSettingsRequest = when (preference) {
    ModelPreference.DictationLive -> UpdateSettingsRequest(
        dictationLiveSttProvider = option.provider,
        dictationLiveSttModel = option.model,
    )
    ModelPreference.RecordingLive -> UpdateSettingsRequest(
        recordingLiveSttProvider = option.provider,
        recordingLiveSttModel = option.model,
    )
    ModelPreference.File -> UpdateSettingsRequest(
        fileSttProvider = option.provider,
        fileSttModel = option.model,
    )
    ModelPreference.DictationPostFilter -> UpdateSettingsRequest(
        dictationPostFilterProvider = option.provider,
        dictationPostFilterModel = option.model,
    )
}

private fun UserSettings.requiresStableTranscriptionReset(): Boolean {
    return dictationLiveSttProvider != STABLE_DICTATION_PROVIDER ||
        dictationLiveSttModel != STABLE_DICTATION_MODEL ||
        recordingLiveSttProvider != STABLE_RECORDING_PROVIDER ||
        recordingLiveSttModel != STABLE_RECORDING_MODEL ||
        fileSttProvider != STABLE_FILE_PROVIDER ||
        fileSttModel != STABLE_FILE_MODEL ||
        !dictationPostFilterEnabled ||
        dictationPostFilterProvider != STABLE_POST_FILTER_PROVIDER ||
        dictationPostFilterModel != STABLE_POST_FILTER_MODEL
}

private fun stableTranscriptionUpdateRequest(): UpdateSettingsRequest {
    return UpdateSettingsRequest(
        dictationLiveSttProvider = STABLE_DICTATION_PROVIDER,
        dictationLiveSttModel = STABLE_DICTATION_MODEL,
        recordingLiveSttProvider = STABLE_RECORDING_PROVIDER,
        recordingLiveSttModel = STABLE_RECORDING_MODEL,
        fileSttProvider = STABLE_FILE_PROVIDER,
        fileSttModel = STABLE_FILE_MODEL,
        dictationPostFilterEnabled = true,
        dictationPostFilterProvider = STABLE_POST_FILTER_PROVIDER,
        dictationPostFilterModel = STABLE_POST_FILTER_MODEL,
    )
}

@Composable
private fun languageLabel(code: String): String = when (code) {
    "multi" -> stringResource(R.string.language_multi)
    "en" -> stringResource(R.string.language_en)
    "ru" -> stringResource(R.string.language_ru)
    "es" -> stringResource(R.string.language_es)
    "fr" -> stringResource(R.string.language_fr)
    "de" -> stringResource(R.string.language_de)
    "ja" -> stringResource(R.string.language_ja)
    "ko" -> stringResource(R.string.language_ko)
    "zh" -> stringResource(R.string.language_zh)
    else -> code
}
