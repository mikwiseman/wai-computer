package `is`.waiwai.computer.qa

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import `is`.waiwai.computer.data.CompanionStreamEvent
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

private val STARTER_PROMPTS = listOf(
    "What did I commit to this week?",
    "Summarize my last meeting.",
    "What patterns show up in my reflections?",
    "When did I first mention pricing?",
)

private data class UiMessage(
    val id: String,
    val sender: String,
    val body: String,
    val citations: List<UiCitation> = emptyList(),
)

private data class UiCitation(
    val index: Int,
    val segmentId: String,
    val recordingId: String,
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
    val messages = remember { mutableStateListOf<UiMessage>() }
    var question by remember { mutableStateOf("") }
    var activeChatId by remember { mutableStateOf<String?>(null) }
    var streamingText by remember { mutableStateOf("") }
    var streamingCitations by remember { mutableStateOf(listOf<UiCitation>()) }
    var streamingToolNotes by remember { mutableStateOf(listOf<String>()) }
    var error by remember { mutableStateOf<String?>(null) }
    var isStreaming by remember { mutableStateOf(false) }

    LaunchedEffect(isGuest) {
        if (isGuest) return@LaunchedEffect
        runCatching { container.companionApi.listChats() }
            .onSuccess { list ->
                val first = list.chats.firstOrNull() ?: return@onSuccess
                activeChatId = first.id
                runCatching { container.companionApi.getChat(first.id) }
                    .onSuccess { detail ->
                        messages.clear()
                        messages.addAll(detail.messages.map { it.toUi(context) })
                    }
            }
    }

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
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                if (isGuest) {
                    Text(text = stringResource(R.string.wai_locked_title))
                    Text(
                        text = stringResource(R.string.wai_locked_body),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    if (messages.isEmpty() && !isStreaming) {
                        EmptyState(onStarter = { question = it })
                    } else {
                        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            items(messages) { message ->
                                MessageCard(
                                    message = message,
                                    onOpenRecording = onOpenRecording,
                                )
                            }
                        }
                    }
                    if (isStreaming) {
                        StreamingCard(
                            text = streamingText,
                            toolNotes = streamingToolNotes,
                            citations = streamingCitations,
                            onOpenRecording = onOpenRecording,
                        )
                    }
                    error?.let {
                        Text(it, color = MaterialTheme.colorScheme.error)
                    }
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        OutlinedTextField(
                            value = question,
                            onValueChange = { question = it },
                            modifier = Modifier.weight(1f),
                            label = { Text(stringResource(R.string.wai_input_hint)) },
                            enabled = !isStreaming,
                        )
                        Button(
                            enabled = !isStreaming && question.isNotBlank(),
                            onClick = {
                                val prompt = question.trim()
                                if (prompt.isEmpty()) return@Button
                                scope.launch {
                                    error = null
                                    isStreaming = true
                                    streamingText = ""
                                    streamingCitations = emptyList()
                                    streamingToolNotes = emptyList()

                                    val chatId = activeChatId ?: runCatching {
                                        container.companionApi.createChat().also {
                                            activeChatId = it.id
                                        }.id
                                    }.getOrElse {
                                        error = it.message ?: "Could not start chat"
                                        isStreaming = false
                                        return@launch
                                    }

                                    messages += UiMessage(
                                        id = "local-${System.currentTimeMillis()}",
                                        sender = context.getString(R.string.wai_you),
                                        body = prompt,
                                    )
                                    question = ""

                                    runCatching {
                                        container.companionApi.streamMessage(chatId, prompt)
                                            .collect { event ->
                                                when (event) {
                                                    is CompanionStreamEvent.TurnStart -> Unit
                                                    is CompanionStreamEvent.ToolCall -> {
                                                        streamingToolNotes = streamingToolNotes +
                                                            "${event.tool} (${event.callId})…"
                                                    }
                                                    is CompanionStreamEvent.ToolResult -> {
                                                        streamingToolNotes = streamingToolNotes.map { note ->
                                                            if (note.contains(event.callId)) {
                                                                "$note → ${event.summary}"
                                                            } else {
                                                                note
                                                            }
                                                        }
                                                    }
                                                    is CompanionStreamEvent.Token -> {
                                                        streamingText += event.text
                                                    }
                                                    is CompanionStreamEvent.Citation -> {
                                                        streamingCitations = streamingCitations + UiCitation(
                                                            index = event.index,
                                                            segmentId = event.segmentId,
                                                            recordingId = event.recordingId,
                                                        )
                                                    }
                                                    is CompanionStreamEvent.Done -> Unit
                                                    is CompanionStreamEvent.Error -> {
                                                        error = event.message
                                                    }
                                                }
                                            }
                                        val refreshed = container.companionApi.getChat(chatId)
                                        messages.clear()
                                        messages.addAll(refreshed.messages.map { it.toUi(context) })
                                    }.onFailure { error = it.message }

                                    streamingText = ""
                                    streamingCitations = emptyList()
                                    streamingToolNotes = emptyList()
                                    isStreaming = false
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

@Composable
private fun EmptyState(onStarter: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = "What do you want to know?",
            style = MaterialTheme.typography.titleMedium,
        )
        Text(
            text = "Wai answers from your recordings.",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(modifier = Modifier.height(4.dp))
        STARTER_PROMPTS.forEach { prompt ->
            TextButton(onClick = { onStarter(prompt) }) {
                Text(prompt)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MessageCard(message: UiMessage, onOpenRecording: (String) -> Unit) {
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
            if (message.citations.isNotEmpty()) {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    message.citations.forEach { citation ->
                        AssistChip(
                            onClick = { onOpenRecording(citation.recordingId) },
                            label = { Text("[${citation.index}]") },
                        )
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun StreamingCard(
    text: String,
    toolNotes: List<String>,
    citations: List<UiCitation>,
    onOpenRecording: (String) -> Unit,
) {
    Card {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "Wai",
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.SemiBold,
            )
            if (text.isEmpty()) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator()
                    Text(
                        text = stringResource(R.string.wai_loading),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                toolNotes.forEach { note ->
                    Text(
                        text = note,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                Text(text)
                if (citations.isNotEmpty()) {
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        citations.forEach { citation ->
                            AssistChip(
                                onClick = { onOpenRecording(citation.recordingId) },
                                label = { Text("[${citation.index}]") },
                            )
                        }
                    }
                }
            }
        }
    }
}

private fun `is`.waiwai.computer.data.CompanionMessage.toUi(
    context: android.content.Context,
): UiMessage {
    val plainText = extractPlainText(content)
    val sender = when (role) {
        "user" -> context.getString(R.string.wai_you)
        else -> context.getString(R.string.wai_assistant)
    }
    return UiMessage(
        id = id,
        sender = sender,
        body = plainText,
        citations = citations.map { citation ->
            UiCitation(
                index = citation.citationIndex,
                segmentId = citation.segmentId.orEmpty(),
                recordingId = citation.recordingId.orEmpty(),
            )
        },
    )
}

private fun extractPlainText(content: JsonElement): String {
    return when (content) {
        is JsonPrimitive -> content.contentOrNull.orEmpty()
        is JsonArray -> content.joinToString(separator = "") { item ->
            when (item) {
                is JsonObject -> item["text"]?.jsonPrimitive?.contentOrNull.orEmpty()
                is JsonPrimitive -> item.contentOrNull.orEmpty()
                is JsonArray -> ""
            }
        }
        is JsonObject -> content["text"]?.jsonPrimitive?.contentOrNull.orEmpty()
    }
}
