package `is`.waiwai.computer.search

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import `is`.waiwai.computer.R
import `is`.waiwai.computer.data.AppContainer
import `is`.waiwai.computer.data.SearchMode
import `is`.waiwai.computer.data.SearchResult
import `is`.waiwai.computer.ui.TestTags
import `is`.waiwai.computer.ui.components.BannerCard
import `is`.waiwai.computer.ui.components.BannerVariant
import `is`.waiwai.computer.ui.components.EmptyState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(
    modifier: Modifier = Modifier,
    container: AppContainer,
    isGuest: Boolean,
    onOpenRecording: (String) -> Unit,
    viewModel: SearchViewModel? = null,
) {
    val resolvedViewModel = viewModel ?: remember(container) {
        SearchViewModel(container.waiApi)
    }
    val uiState by resolvedViewModel.uiState.collectAsState()
    val keyboard = LocalSoftwareKeyboardController.current

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            text = stringResource(R.string.tab_search),
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(top = 24.dp),
        )

        if (isGuest) {
            BannerCard(
                title = stringResource(R.string.search_guest_title),
                body = stringResource(R.string.search_guest_body),
                variant = BannerVariant.Info,
            )
            return@Column
        }

        OutlinedTextField(
            value = uiState.query,
            onValueChange = resolvedViewModel::updateQuery,
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 560.dp)
                .testTag(TestTags.SearchQueryField),
            placeholder = { Text(stringResource(R.string.search_input_hint)) },
            leadingIcon = {
                Icon(Icons.Outlined.Search, contentDescription = null)
            },
            trailingIcon = {
                if (uiState.query.isNotEmpty()) {
                    IconButton(
                        onClick = resolvedViewModel::clear,
                        modifier = Modifier.testTag(TestTags.SearchClearButton),
                    ) {
                        Icon(
                            imageVector = Icons.Outlined.Close,
                            contentDescription = stringResource(R.string.search_clear),
                        )
                    }
                }
            },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                imeAction = ImeAction.Search,
                capitalization = KeyboardCapitalization.Sentences,
            ),
            keyboardActions = KeyboardActions(
                onSearch = {
                    resolvedViewModel.submit()
                    keyboard?.hide()
                },
            ),
        )

        SingleChoiceSegmentedButtonRow(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 560.dp),
        ) {
            SearchMode.entries.forEachIndexed { index, mode ->
                SegmentedButton(
                    selected = uiState.mode == mode,
                    onClick = { resolvedViewModel.selectMode(mode) },
                    shape = SegmentedButtonDefaults.itemShape(index, SearchMode.entries.size),
                    modifier = Modifier.testTag(
                        when (mode) {
                            SearchMode.Hybrid -> TestTags.SearchModeHybrid
                            SearchMode.Semantic -> TestTags.SearchModeSemantic
                            SearchMode.Fulltext -> TestTags.SearchModeFulltext
                        },
                    ),
                    label = { Text(stringResource(modeLabel(mode))) },
                )
            }
        }

        if (uiState.error != null) {
            BannerCard(
                title = uiState.error.orEmpty(),
                body = null,
                variant = BannerVariant.Error,
            )
        }

        when {
            uiState.isLoading -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(top = 32.dp),
                    contentAlignment = Alignment.TopCenter,
                ) {
                    CircularProgressIndicator()
                }
            }
            uiState.hasSearched && uiState.results.isEmpty() -> {
                EmptyState(
                    title = stringResource(R.string.search_no_results_title),
                    body = stringResource(R.string.search_no_results_body),
                    actionLabel = null,
                    onAction = null,
                    modifier = Modifier.padding(top = 32.dp),
                )
            }
            !uiState.hasSearched -> {
                EmptyState(
                    title = stringResource(R.string.search_empty_title),
                    body = stringResource(R.string.search_empty_body),
                    actionLabel = null,
                    onAction = null,
                    modifier = Modifier.padding(top = 32.dp),
                )
            }
            else -> {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .widthIn(max = 560.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    items(
                        uiState.results,
                        key = { "${it.recordingId}-${it.segmentId}" },
                    ) { result ->
                        SearchResultCard(
                            result = result,
                            onClick = { onOpenRecording(result.recordingId) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SearchResultCard(
    result: SearchResult,
    onClick: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag(TestTags.searchResultItem(result.recordingId, result.segmentId))
            .clickable(onClick = onClick),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Text(
                    text = result.recordingTitle?.takeIf { it.isNotBlank() }
                        ?: stringResource(R.string.detail_untitled),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                Spacer(modifier = Modifier.height(0.dp))
                Text(
                    text = stringResource(
                        R.string.search_score_format,
                        (result.score * 100).toInt().coerceIn(0, 100),
                    ),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            if (!result.speaker.isNullOrBlank()) {
                Text(
                    text = result.speaker,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            Text(
                text = result.content,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 3,
            )
        }
    }
}

private fun modeLabel(mode: SearchMode): Int = when (mode) {
    SearchMode.Hybrid -> R.string.search_mode_hybrid
    SearchMode.Semantic -> R.string.search_mode_semantic
    SearchMode.Fulltext -> R.string.search_mode_fulltext
}
