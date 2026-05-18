package `is`.waiwai.computer

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performImeAction
import androidx.compose.ui.test.performTextInput
import `is`.waiwai.computer.data.SearchResult
import `is`.waiwai.computer.search.SearchScreen
import `is`.waiwai.computer.search.SearchViewModel
import `is`.waiwai.computer.ui.TestTags
import `is`.waiwai.computer.ui.theme.WaiTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Rule
import org.junit.Test

class SearchInstrumentedTest {
    @get:Rule
    val composeRule = createComposeRule()

    private lateinit var fixture: TestAppFixture

    @After
    fun tearDown() {
        if (::fixture.isInitialized) fixture.cleanup()
    }

    @Test
    fun guest_sees_locked_state() {
        fixture = createTestAppFixture()
        composeRule.setContent {
            WaiTheme {
                SearchScreen(
                    container = fixture.container,
                    isGuest = true,
                    onOpenRecording = {},
                    viewModel = SearchViewModel(fixture.container.waiApi),
                )
            }
        }

        composeRule.onNodeWithText(string(R.string.search_guest_title)).assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.search_guest_body)).assertIsDisplayed()
    }

    @Test
    fun authenticated_user_can_submit_query_and_see_results() {
        fixture = createTestAppFixture(
            initialSearchResults = listOf(
                SearchResult(
                    recordingId = "rec-1",
                    recordingTitle = "Stand-up",
                    recordingType = "meeting",
                    segmentId = "seg-1",
                    speaker = "Mik",
                    content = "We shipped the Android v1.0 today.",
                    startMs = 0,
                    endMs = 4500,
                    score = 0.88,
                ),
            ),
        )
        runBlocking {
            fixture.secureTokenStore.writeAccessToken("access-token")
            fixture.secureTokenStore.writeRefreshToken("refresh-token")
        }
        composeRule.setContent {
            WaiTheme {
                SearchScreen(
                    container = fixture.container,
                    isGuest = false,
                    onOpenRecording = {},
                    viewModel = SearchViewModel(fixture.container.waiApi),
                )
            }
        }

        composeRule.onNodeWithTag(TestTags.SearchQueryField).performTextInput("android")
        composeRule.onNodeWithTag(TestTags.SearchQueryField).performImeAction()

        composeRule.waitUntil(timeoutMillis = 5_000) {
            composeRule.onAllNodes(androidx.compose.ui.test.hasText("Stand-up"))
                .fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText("Stand-up").assertIsDisplayed()
        composeRule.onNodeWithText("We shipped the Android v1.0 today.").assertIsDisplayed()
        composeRule.onNodeWithText("88%").assertIsDisplayed()
    }

    @Test
    fun selecting_a_mode_chip_keeps_the_screen_responsive() {
        fixture = createTestAppFixture()
        runBlocking {
            fixture.secureTokenStore.writeAccessToken("access-token")
            fixture.secureTokenStore.writeRefreshToken("refresh-token")
        }
        composeRule.setContent {
            WaiTheme {
                SearchScreen(
                    container = fixture.container,
                    isGuest = false,
                    onOpenRecording = {},
                    viewModel = SearchViewModel(fixture.container.waiApi),
                )
            }
        }

        composeRule.onNodeWithTag(TestTags.SearchModeSemantic).performClick()
        composeRule.onNodeWithText(string(R.string.search_empty_title)).assertIsDisplayed()
    }

    @Test
    fun clearing_the_query_resets_the_screen() {
        fixture = createTestAppFixture(
            initialSearchResults = listOf(
                SearchResult(
                    recordingId = "rec-1",
                    recordingTitle = "Note",
                    recordingType = "note",
                    segmentId = "seg-1",
                    speaker = null,
                    content = "Pricing notes for the v1.0 launch.",
                    startMs = 0,
                    endMs = 1000,
                    score = 0.5,
                ),
            ),
        )
        runBlocking {
            fixture.secureTokenStore.writeAccessToken("access-token")
            fixture.secureTokenStore.writeRefreshToken("refresh-token")
        }
        composeRule.setContent {
            WaiTheme {
                SearchScreen(
                    container = fixture.container,
                    isGuest = false,
                    onOpenRecording = {},
                    viewModel = SearchViewModel(fixture.container.waiApi),
                )
            }
        }

        composeRule.onNodeWithTag(TestTags.SearchQueryField).performTextInput("pricing")
        composeRule.onNodeWithTag(TestTags.SearchQueryField).performImeAction()
        composeRule.waitUntil(timeoutMillis = 5_000) {
            composeRule.onAllNodes(androidx.compose.ui.test.hasText("Note"))
                .fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag(TestTags.SearchClearButton).performClick()
        composeRule.onNodeWithText(string(R.string.search_empty_title)).assertIsDisplayed()
    }
}
