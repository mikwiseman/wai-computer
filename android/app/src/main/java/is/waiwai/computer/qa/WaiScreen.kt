package `is`.waiwai.computer.qa

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import `is`.waiwai.computer.R
import `is`.waiwai.computer.data.AppContainer
import `is`.waiwai.computer.data.QASource
import kotlinx.coroutines.launch

private data class ChatMessage(
    val sender: String,
    val body: String,
    val sources: List<QASource> = emptyList(),
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun WaiScreen(
    modifier: Modifier = Modifier,
    container: AppContainer,
    isGuest: Boolean,
    onOpenRecording: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val messages = remember { mutableStateListOf<ChatMessage>() }
    var question by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var isLoading by remember { mutableStateOf(false) }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            text = stringResource(R.string.tab_wai),
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
        )
        Card {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                if (isGuest) {
                    Text(text = stringResource(R.string.wai_locked_title))
                    Text(
                        text = stringResource(R.string.wai_locked_body),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    if (messages.isEmpty()) {
                        Text(text = stringResource(R.string.onboarding_body_3))
                    } else {
                        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            items(messages) { message ->
                                Card {
                                    Column(
                                        modifier = Modifier.padding(12.dp),
                                        verticalArrangement = Arrangement.spacedBy(8.dp),
                                    ) {
                                        Text(
                                            text = message.sender,
                                            style = MaterialTheme.typography.labelLarge,
                                            fontWeight = FontWeight.SemiBold,
                                        )
                                        Text(message.body)
                                        if (message.sources.isNotEmpty()) {
                                            FlowRow(
                                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                                verticalArrangement = Arrangement.spacedBy(8.dp),
                                            ) {
                                                message.sources.forEach { source ->
                                                    AssistChip(
                                                        onClick = { onOpenRecording(source.recordingId) },
                                                        label = {
                                                            Text(
                                                                source.recordingTitle
                                                                    ?: stringResource(R.string.detail_untitled),
                                                            )
                                                        },
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    if (isLoading) {
                        Card {
                            Column(
                                modifier = Modifier.padding(12.dp),
                                verticalArrangement = Arrangement.spacedBy(12.dp),
                            ) {
                                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                    CircularProgressIndicator()
                                    Text(stringResource(R.string.wai_loading))
                                }
                                Spacer(modifier = Modifier.height(4.dp))
                            }
                        }
                    }
                    if (error != null) {
                        Text(error.orEmpty(), color = MaterialTheme.colorScheme.error)
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                        OutlinedTextField(
                            value = question,
                            onValueChange = { question = it },
                            modifier = Modifier.weight(1f),
                            label = { Text(stringResource(R.string.wai_input_hint)) },
                        )
                        Button(
                            onClick = {
                                val prompt = question.trim()
                                if (prompt.isEmpty()) return@Button
                                scope.launch {
                                    messages += ChatMessage(
                                        sender = context.getString(R.string.wai_you),
                                        body = prompt,
                                    )
                                    question = ""
                                    isLoading = true
                                    runCatching { container.waiApi.askDatabase(prompt) }
                                        .onSuccess {
                                            messages += ChatMessage(
                                                sender = context.getString(R.string.wai_assistant),
                                                body = it.answer,
                                                sources = it.sources,
                                            )
                                            error = null
                                        }
                                        .onFailure { throwable ->
                                            error = throwable.message
                                        }
                                    isLoading = false
                                }
                            },
                        ) {
                            Text(stringResource(R.string.wai_send))
                        }
                    }
                }
            }
        }
    }
}
