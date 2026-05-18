package `is`.waiwai.computer.recording

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import `is`.waiwai.computer.R
import `is`.waiwai.computer.ui.TestTags
import `is`.waiwai.computer.ui.components.BannerCard
import `is`.waiwai.computer.ui.components.BannerVariant

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ImportSheet(
    viewModel: ImportViewModel,
    onDismiss: () -> Unit,
    onImported: (recordingId: String) -> Unit,
) {
    val context = LocalContext.current
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val uiState by viewModel.uiState.collectAsState()

    val picker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        viewModel.import(UriImportSource(context.applicationContext, uri))
    }

    LaunchedEffect(uiState) {
        val state = uiState
        if (state is ImportUiState.Success) {
            val id = state.recording.id
            viewModel.consumeSuccess()
            onImported(id)
        }
    }

    ModalBottomSheet(
        onDismissRequest = {
            if (uiState !is ImportUiState.Uploading) {
                viewModel.reset()
                onDismiss()
            }
        },
        sheetState = sheetState,
        modifier = Modifier.testTag(TestTags.ImportSheet),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                text = stringResource(R.string.import_audio),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = stringResource(R.string.import_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            when (val state = uiState) {
                is ImportUiState.Idle -> {
                    Button(
                        onClick = { picker.launch(AUDIO_MIME_TYPES) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag(TestTags.ImportPickFileButton),
                    ) {
                        Text(stringResource(R.string.import_pick_file))
                    }
                }
                is ImportUiState.Uploading -> {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        CircularProgressIndicator()
                        Text(stringResource(R.string.import_uploading, state.filename))
                    }
                }
                is ImportUiState.Error -> {
                    BannerCard(
                        title = stringResource(R.string.import_failure_prefix),
                        body = state.message,
                        variant = BannerVariant.Error,
                    )
                    Button(
                        onClick = { picker.launch(AUDIO_MIME_TYPES) },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(stringResource(R.string.import_pick_file))
                    }
                }
                is ImportUiState.Success -> Unit
            }

            if (uiState !is ImportUiState.Uploading) {
                TextButton(
                    onClick = {
                        viewModel.reset()
                        onDismiss()
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag(TestTags.ImportDoneButton),
                ) {
                    Text(stringResource(R.string.common_cancel))
                }
            }
        }
    }
}

private val AUDIO_MIME_TYPES = arrayOf(
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/opus",
    "audio/flac",
    "audio/webm",
    "audio/*",
)

private class UriImportSource(
    private val context: Context,
    private val uri: Uri,
) : ImportSource {
    override val displayName: String = resolveDisplayName(context.contentResolver, uri)
    override val extension: String? = displayName.substringAfterLast('.', "").ifBlank { null }

    override suspend fun openInputStream() = context.contentResolver.openInputStream(uri)

    companion object {
        fun resolveDisplayName(resolver: ContentResolver, uri: Uri): String {
            val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { cursor ->
                    if (cursor.moveToFirst()) {
                        val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        if (index >= 0) cursor.getString(index) else null
                    } else {
                        null
                    }
                }
            return name?.takeIf { it.isNotBlank() }
                ?: uri.lastPathSegment?.substringAfterLast('/').orEmpty()
                    .ifBlank { "imported-audio" }
        }
    }
}
