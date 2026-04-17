package `is`.waiwai.say

import android.Manifest
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.rule.GrantPermissionRule
import `is`.waiwai.say.recording.Phase
import `is`.waiwai.say.recording.RecordingViewModel
import `is`.waiwai.say.sync.PendingSyncWorkerScheduler
import `is`.waiwai.say.ui.TestTags
import `is`.waiwai.say.ui.WaiAndroidApp
import `is`.waiwai.say.ui.theme.WaiTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

class OnboardingInstrumentedTest {
    @get:Rule
    val permissionRule: GrantPermissionRule = GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO)

    @get:Rule
    val composeRule = createComposeRule()

    private lateinit var fixture: TestAppFixture
    private lateinit var recordingViewModel: RecordingViewModel

    @Before
    fun setUp() {
        fixture = createTestAppFixture()
        runBlocking {
            fixture.authStore.bootstrap()
        }
        recordingViewModel = RecordingViewModel(
            application = fixture.application,
            authStore = fixture.authStore,
            settingsStore = fixture.settingsStore,
            waiApi = fixture.container.waiApi,
            localRecordingStore = fixture.container.localRecordingStore,
            syncScheduler = PendingSyncWorkerScheduler(fixture.application),
            audioRecorderFactory = { TestAudioRecorder() },
            webSocketFactory = { TestWebSocketManager() },
        )
    }

    @After
    fun tearDown() {
        fixture.cleanup()
    }

    @Test
    fun onboarding_guest_recording_and_sign_in_shows_migration_banner() {
        composeRule.setContent {
            WaiTheme {
                WaiAndroidApp(
                    container = fixture.container,
                    pendingMagicLinkToken = null,
                    onMagicLinkConsumed = {},
                    recordingViewModel = recordingViewModel,
                )
            }
        }

        composeRule.onNodeWithTag(TestTags.OnboardingPrimaryButton).performClick()
        composeRule.onNodeWithTag(TestTags.OnboardingPrimaryButton).performClick()
        composeRule.onNodeWithText(string(R.string.common_get_started)).performClick()
        composeRule.onNodeWithTag(TestTags.AuthChoiceTryGuestButton).performClick()
        composeRule.onNodeWithTag(TestTags.GuestConfirmButton).performClick()

        composeRule.onNodeWithTag(TestTags.RecordButton).performClick()
        composeRule.waitUntil(timeoutMillis = 5_000) {
            recordingViewModel.uiState.value.phase == Phase.Recording
        }
        composeRule.onNodeWithTag(TestTags.RecordButton).performClick()
        composeRule.waitUntil(timeoutMillis = 5_000) {
            runBlocking { fixture.container.localRecordingStore.listPending().isNotEmpty() }
        }

        composeRule.onNodeWithText(string(R.string.tab_settings)).performClick()
        composeRule.onNodeWithTag(TestTags.SettingsSignInButton).performClick()
        composeRule.onNodeWithText(string(R.string.auth_sign_in)).performClick()
        composeRule.onNodeWithTag(TestTags.AuthEmailField).performTextInput("mik@example.com")
        composeRule.onNodeWithTag(TestTags.AuthPasswordField).performTextInput("password123")
        composeRule.onNodeWithTag(TestTags.AuthSubmitButton).performClick()

        composeRule.waitUntil(timeoutMillis = 5_000) {
            composeRule.onAllNodesWithText(string(R.string.auth_migrating_guest_recordings))
                .fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText(string(R.string.auth_migrating_guest_recordings)).assertExists()
    }
}
