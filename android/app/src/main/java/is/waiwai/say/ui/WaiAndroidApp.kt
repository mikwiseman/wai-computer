package is.waiwai.say.ui

import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import is.waiwai.say.data.DigitalAgent
import is.waiwai.say.data.RealtimeVoiceSession
import is.waiwai.say.data.RecordingSummary
import is.waiwai.say.data.SettingsStore
import is.waiwai.say.data.UserApp
import is.waiwai.say.data.WaiApi
import kotlinx.coroutines.launch

private enum class AndroidTab(val label: String) {
    Wai("Wai"),
    Library("Library"),
    Agents("Agents"),
    Apps("Apps"),
    Settings("Settings"),
}

data class AndroidMessage(
    val id: String,
    val role: String,
    val content: String,
    val meta: String? = null,
)

@Composable
fun WaiAndroidApp(
    api: WaiApi,
    settingsStore: SettingsStore,
) {
    var selectedTab by rememberSaveable { mutableStateOf(AndroidTab.Wai) }

    MaterialTheme {
        Scaffold(
            topBar = {
                AppTopBar(selectedTab.label)
            },
            bottomBar = {
                NavigationBar {
                    AndroidTab.entries.forEach { tab ->
                        NavigationBarItem(
                            selected = selectedTab == tab,
                            onClick = { selectedTab = tab },
                            label = { Text(tab.label) },
                            icon = {}
                        )
                    }
                }
            }
        ) { innerPadding ->
            Surface(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding)
            ) {
                when (selectedTab) {
                    AndroidTab.Wai -> WaiScreen(api)
                    AndroidTab.Library -> LibraryScreen(api)
                    AndroidTab.Agents -> AgentsScreen(api)
                    AndroidTab.Apps -> AppsScreen(api)
                    AndroidTab.Settings -> SettingsScreen(settingsStore)
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AppTopBar(title: String) {
    TopAppBar(
        title = { Text(title) },
    )
}

@Composable
private fun WaiScreen(api: WaiApi) {
    val scope = rememberCoroutineScope()
    val messages = remember { mutableStateListOf<AndroidMessage>() }
    var input by rememberSaveable { mutableStateOf("") }
    var sessionId by rememberSaveable { mutableStateOf<String?>(null) }
    var voiceSession by remember { mutableStateOf<RealtimeVoiceSession?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        if (messages.isEmpty()) {
            EmptyStateCard(
                title = "Talk to Wai",
                body = "Use one dialogue for apps, deploys, summaries, and agent runs."
            )
            Spacer(modifier = Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                QuickActionButton("Landing") { input = "Create a landing page and prepare it for publish." }
                QuickActionButton("App") { input = "Create a CRM app for my clients." }
            }
            Spacer(modifier = Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                QuickActionButton("Voice") {
                    scope.launch {
                        busy = true
                        runCatching { api.createRealtimeVoiceSession("conversation") }
                            .onSuccess { voiceSession = it; error = null }
                            .onFailure { error = it.message }
                        busy = false
                    }
                }
                QuickActionButton("Record") {
                    scope.launch {
                        busy = true
                        runCatching { api.createRealtimeVoiceSession("recording") }
                            .onSuccess { voiceSession = it; error = null }
                            .onFailure { error = it.message }
                        busy = false
                    }
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(messages, key = { it.id }) { message ->
                    MessageBubble(message)
                }
            }
        }

        voiceSession?.let {
            Spacer(modifier = Modifier.height(12.dp))
            Card {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("Realtime voice session ready", fontWeight = FontWeight.SemiBold)
                    Text(
                        "Provider ${it.provider}, mode ${it.mode}, agent ${it.agentId}, expires in ${it.expiresInSeconds / 60}m.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        error?.let {
            Spacer(modifier = Modifier.height(12.dp))
            Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        }

        Spacer(modifier = Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Ask Wai to do something…") },
            )
            Button(
                onClick = {
                    val question = input.trim()
                    if (question.isEmpty()) return@Button
                    scope.launch {
                        busy = true
                        messages += AndroidMessage(id = "u-${System.nanoTime()}", role = "user", content = question)
                        input = ""
                        runCatching { api.sendAgentMessage(question, sessionId) }
                            .onSuccess { result ->
                                sessionId = result.sessionId
                                messages += AndroidMessage(
                                    id = "a-${System.nanoTime()}",
                                    role = "assistant",
                                    content = result.response,
                                    meta = "${result.intent} • ${result.toolCalls} tools"
                                )
                                error = null
                            }
                            .onFailure { error = it.message }
                        busy = false
                    }
                },
                enabled = !busy
            ) {
                Text(if (busy) "…" else "Send")
            }
        }
    }
}

@Composable
private fun LibraryScreen(api: WaiApi) {
    var recordings by remember { mutableStateOf<List<RecordingSummary>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        runCatching { api.listRecordings() }
            .onSuccess {
                recordings = it
                error = null
            }
            .onFailure { error = it.message }
    }

    if (recordings.isEmpty()) {
        EmptyStateCard(
            title = "Library",
            body = error ?: "No recordings loaded yet. Configure auth in Settings and refresh."
        )
    } else {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            items(recordings, key = { it.id }) { recording ->
                Card {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(recording.title ?: "Untitled", fontWeight = FontWeight.SemiBold)
                        Text(
                            "${recording.type} • ${recording.status}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun AgentsScreen(api: WaiApi) {
    val scope = rememberCoroutineScope()
    var agents by remember { mutableStateOf<List<DigitalAgent>>(emptyList()) }
    var description by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun reload() {
        runCatching { api.listAgents() }
            .onSuccess {
                agents = it
                error = null
            }
            .onFailure { error = it.message }
    }

    LaunchedEffect(Unit) { reload() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Card {
            Column(modifier = Modifier.padding(12.dp)) {
                Text("Create Agent", fontWeight = FontWeight.SemiBold)
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = description,
                    onValueChange = { description = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("Check important projects every morning…") },
                )
                Spacer(modifier = Modifier.height(8.dp))
                Button(
                    onClick = {
                        scope.launch {
                            runCatching { api.createAgent(description.trim()) }
                                .onSuccess {
                                    description = ""
                                    reload()
                                }
                                .onFailure { error = it.message }
                        }
                    },
                    enabled = description.isNotBlank()
                ) {
                    Text("Create")
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))
        error?.let {
            Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            Spacer(modifier = Modifier.height(8.dp))
        }

        if (agents.isEmpty()) {
            EmptyStateCard("Agents", "No agents yet.")
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(agents, key = { it.id }) { agent ->
                    Card {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Text(agent.name, fontWeight = FontWeight.SemiBold)
                            Text(agent.description, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Spacer(modifier = Modifier.height(6.dp))
                            Text("${agent.cronExpression ?: agent.scheduleType} • ${agent.runCount} runs", style = MaterialTheme.typography.bodySmall)
                            Spacer(modifier = Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(onClick = { scope.launch { runCatching { api.runAgent(agent.id) }.onSuccess { reload() }.onFailure { error = it.message } } }) {
                                    Text("Run")
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AppsScreen(api: WaiApi) {
    val scope = rememberCoroutineScope()
    var apps by remember { mutableStateOf<List<UserApp>>(emptyList()) }
    var newAppName by rememberSaveable { mutableStateOf("") }
    var newAppDescription by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun reload() {
        runCatching { api.listApps() }
            .onSuccess {
                apps = it
                error = null
            }
            .onFailure { error = it.message }
    }

    LaunchedEffect(Unit) { reload() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Card {
            Column(modifier = Modifier.padding(12.dp)) {
                Text("Create App", fontWeight = FontWeight.SemiBold)
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = newAppName,
                    onValueChange = { newAppName = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("Habit Tracker") },
                )
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = newAppDescription,
                    onValueChange = { newAppDescription = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("What this app is for") },
                )
                Spacer(modifier = Modifier.height(8.dp))
                Button(
                    onClick = {
                        scope.launch {
                            runCatching { api.createApp(newAppName.trim(), newAppDescription.trim().ifBlank { null }) }
                                .onSuccess {
                                    newAppName = ""
                                    newAppDescription = ""
                                    reload()
                                }
                                .onFailure { error = it.message }
                        }
                    },
                    enabled = newAppName.isNotBlank()
                ) {
                    Text("Create Draft")
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))
        error?.let {
            Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            Spacer(modifier = Modifier.height(8.dp))
        }

        if (apps.isEmpty()) {
            EmptyStateCard("Apps", "No apps yet.")
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(apps, key = { it.id }) { app ->
                    Card {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Text("${app.icon ?: "📦"} ${app.displayName}", fontWeight = FontWeight.SemiBold)
                            app.description?.takeIf { it.isNotBlank() }?.let {
                                Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Spacer(modifier = Modifier.height(6.dp))
                            Text("${app.status} • ${app.visibility} • ${app.itemCount} items", style = MaterialTheme.typography.bodySmall)
                            Spacer(modifier = Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(onClick = {
                                    scope.launch {
                                        runCatching { api.publishApp(app.id, app.visibility, app.appUrl) }
                                            .onSuccess { reload() }
                                            .onFailure { error = it.message }
                                    }
                                }) {
                                    Text(if (app.status == "live") "Republish" else "Publish")
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsScreen(settingsStore: SettingsStore) {
    var baseUrl by rememberSaveable { mutableStateOf(settingsStore.baseUrl) }
    var accessToken by rememberSaveable { mutableStateOf(settingsStore.accessToken) }
    var saved by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        Card {
            Column(modifier = Modifier.padding(12.dp)) {
                Text("Connection", fontWeight = FontWeight.SemiBold)
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it; saved = false },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("API base URL") },
                )
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = accessToken,
                    onValueChange = { accessToken = it; saved = false },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Access token") },
                )
                Spacer(modifier = Modifier.height(8.dp))
                Button(onClick = {
                    settingsStore.baseUrl = baseUrl
                    settingsStore.accessToken = accessToken
                    saved = true
                }) {
                    Text("Save")
                }
                if (saved) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text("Saved", color = Color(0xFF0F9D58), style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

@Composable
private fun EmptyStateCard(title: String, body: String) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        contentAlignment = Alignment.Center
    ) {
        Card {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(title, fontWeight = FontWeight.SemiBold)
                Spacer(modifier = Modifier.height(6.dp))
                Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun QuickActionButton(label: String, action: () -> Unit) {
    Box(
        modifier = Modifier
            .background(MaterialTheme.colorScheme.secondaryContainer, RoundedCornerShape(999.dp))
            .clickable(onClick = action)
            .padding(horizontal = 14.dp, vertical = 10.dp)
    ) {
        Text(label)
    }
}

@Composable
private fun MessageBubble(message: AndroidMessage) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (message.role == "user") Arrangement.End else Arrangement.Start
    ) {
        Card {
            Column(modifier = Modifier.padding(12.dp)) {
                Text(message.content)
                message.meta?.let {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}
