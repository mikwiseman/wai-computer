package `is`.waiwai.say

import android.Manifest
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.rule.GrantPermissionRule
import `is`.waiwai.say.recording.RecordingScreen
import `is`.waiwai.say.recording.RecordingViewModel
import `is`.waiwai.say.sync.PendingSyncWorkerScheduler
import `is`.waiwai.say.ui.TestTags
import `is`.waiwai.say.ui.theme.WaiTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

class RecordingFlowInstrumentedTest {
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
            fixture.authStore.login("mik@example.com", "password123")
        }
        recordingViewModel = RecordingViewModel(
            application = fixture.application,
            authStore = fixture.authStore,
            settingsStore = fixture.settingsStore,
            waiApi = fixture.container.waiApi,
            localRecordingStore = fixture.container.localRecordingStore,
            syncScheduler = PendingSyncWorkerScheduler(fixture.application),
            audioRecorderFactory = { TestAudioRecorder() },
            webSocketFactory = {
                TestWebSocketManager(
                    segments = listOf(
                        `is`.waiwai.say.data.LiveTranscriptSegment(
                            text = "Transcript ready",
                            isFinal = true,
                            startMs = 0,
                            endMs = 1200,
                            confidence = 0.98,
                        ),
                    ),
                )
            },
        )
    }

    @After
    fun tearDown() {
        fixture.cleanup()
    }

    @Test
    fun recording_screen_renders_live_transcript_and_finalizes_cleanly() {
        composeRule.setContent {
            WaiTheme {
                RecordingScreen(
                    container = fixture.container,
                    isGuest = false,
                    viewModel = recordingViewModel,
                )
            }
        }

        composeRule.onNodeWithTag(TestTags.RecordButton).performClick()
        composeRule.waitUntil(timeoutMillis = 5_000) {
            composeRule.onAllNodesWithText("Transcript ready").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText("Transcript ready").assertExists()

        composeRule.onNodeWithTag(TestTags.RecordButton).performClick()
        composeRule.waitUntil(timeoutMillis = 5_000) {
            recordingViewModel.uiState.value.phase == `is`.waiwai.say.recording.Phase.Idle
        }
        composeRule.waitUntil(timeoutMillis = 5_000) {
            fixture.backend.recordings.firstOrNull()?.status == `is`.waiwai.say.data.RecordingStatus.Ready
        }
    }
}
