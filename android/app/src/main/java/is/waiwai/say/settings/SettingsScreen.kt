package `is`.waiwai.say.settings

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import `is`.waiwai.say.BuildConfig
import `is`.waiwai.say.R
import `is`.waiwai.say.auth.AuthState
import `is`.waiwai.say.auth.AuthViewModel
import `is`.waiwai.say.data.AppContainer
import kotlinx.coroutines.launch

private data class StorageSummary(
    val count: Int = 0,
    val sizeMb: Double = 0.0,
)

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
    var showClearCacheConfirm by rememberSaveable { mutableStateOf(false) }
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
                    TextButton(
                        onClick = {
                            context.startActivity(
                                Intent(
                                    Intent.ACTION_SENDTO,
                                    Uri.parse("mailto:support@waiwai.is?subject=Delete%20WaiSay%20account"),
                                ),
                            )
                        },
                    ) {
                        Text(stringResource(R.string.settings_delete_account))
                    }
                }
                is AuthState.Guest,
                AuthState.Onboarding,
                AuthState.Unknown,
                is AuthState.SessionExpired,
                -> {
                    Text(stringResource(R.string.settings_sign_in_sync))
                    Button(onClick = onContinueSignIn, modifier = Modifier.fillMaxWidth()) {
                        Text(stringResource(R.string.guest_banner_sign_in_to_sync))
                    }
                }
            }
        }

        SettingsSectionCard(title = stringResource(R.string.settings_transcription)) {
            TextButton(onClick = { showLanguageSheet = true }) {
                Text(languageLabel(settings.transcriptionLanguage))
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
