package `is`.waiwai.computer

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import `is`.waiwai.computer.data.Recording
import `is`.waiwai.computer.data.RecordingStatus
import `is`.waiwai.computer.data.RecordingType
import `is`.waiwai.computer.library.LibraryScreen
import `is`.waiwai.computer.ui.TestTags
import `is`.waiwai.computer.ui.theme.WaiTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

class LibraryInstrumentedTest {
    @get:Rule
    val composeRule = createComposeRule()

    private lateinit var fixture: TestAppFixture
    private val recordingId = "rec-library-1"

    @Before
    fun setUp() {
        fixture = createTestAppFixture(
            initialRecordings = listOf(
                Recording(
                    id = recordingId,
                    title = "Design sync",
                    type = RecordingType.note,
                    status = RecordingStatus.Ready,
                    durationSeconds = 75,
                    createdAt = "2026-04-17T10:00:00Z",
                ),
            ),
        )
        runBlocking {
            fixture.authStore.login("mik@example.com", "password123")
        }
    }

    @After
    fun tearDown() {
        fixture.cleanup()
    }

    @Test
    fun library_renders_items_and_confirms_swipe_delete() {
        composeRule.setContent {
            WaiTheme {
                LibraryScreen(
                    container = fixture.container,
                    isGuest = false,
                    onSwitchToRecord = {},
                    onOpenRecording = { _, _ -> },
                )
            }
        }

        composeRule.waitUntil(timeoutMillis = 5_000) {
            composeRule.onAllNodesWithTag(TestTags.libraryItem(recordingId))
                .fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText("Design sync").assertExists()

        composeRule.onNodeWithTag(TestTags.libraryItem(recordingId))
            .performTouchInput { swipeLeft() }

        composeRule.onNodeWithText(string(R.string.library_delete_confirm_title)).assertExists()
        composeRule.onNodeWithTag(TestTags.LibraryDeleteConfirmButton).performClick()

        composeRule.waitUntil(timeoutMillis = 5_000) {
            fixture.backend.recordings.none { it.id == recordingId }
        }
        composeRule.onNodeWithTag(TestTags.libraryItem(recordingId)).assertDoesNotExist()
    }
}
