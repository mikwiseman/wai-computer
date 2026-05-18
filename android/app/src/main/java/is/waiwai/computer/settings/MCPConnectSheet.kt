package `is`.waiwai.computer.settings

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import `is`.waiwai.computer.R
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

internal const val MCP_ENDPOINT_URL = "https://wai.computer/mcp"
private const val CLAUDE_AI_CONNECTORS_URL = "https://claude.ai/customize/connectors"

private enum class McpClient(val labelRes: Int, val stepsRes: Int) {
    ClaudeAI(R.string.settings_mcp_client_claudeai, R.string.settings_mcp_steps_claudeai),
    Cursor(R.string.settings_mcp_client_cursor, R.string.settings_mcp_steps_cursor),
    ChatGPT(R.string.settings_mcp_client_chatgpt, R.string.settings_mcp_steps_chatgpt),
    ClaudeCode(R.string.settings_mcp_client_claudecode, R.string.settings_mcp_steps_claudecode),
    Codex(R.string.settings_mcp_client_codex, R.string.settings_mcp_steps_codex),
}

private val cursorSnippet =
    """
    {
      "mcpServers": {
        "waicomputer": {
          "url": "$MCP_ENDPOINT_URL"
        }
      }
    }
    """.trimIndent()

private val claudeCodeSnippet =
    """
    # CLI
    claude mcp add waicomputer $MCP_ENDPOINT_URL

    # Or .mcp.json:
    {
      "mcpServers": {
        "waicomputer": {
          "type": "http",
          "url": "$MCP_ENDPOINT_URL"
        }
      }
    }
    """.trimIndent()

private val codexSnippet =
    """
    codex mcp add waicomputer --url $MCP_ENDPOINT_URL
    codex mcp login waicomputer
    """.trimIndent()

private fun snippetFor(client: McpClient): String? = when (client) {
    McpClient.Cursor -> cursorSnippet
    McpClient.ClaudeCode -> claudeCodeSnippet
    McpClient.Codex -> codexSnippet
    else -> null
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MCPConnectSheet(onDismiss: () -> Unit) {
    val context = LocalContext.current
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scope = rememberCoroutineScope()
    var selectedClient by rememberSaveable { mutableStateOf(McpClient.ClaudeAI) }
    var copiedField by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(copiedField) {
        if (copiedField != null) {
            delay(1500)
            copiedField = null
        }
    }

    fun copy(label: String, value: String, field: String) {
        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText(label, value))
        copiedField = field
    }

    fun shareUrl() {
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, MCP_ENDPOINT_URL)
        }
        context.startActivity(
            Intent.createChooser(intent, context.getString(R.string.settings_mcp_share_chooser))
        )
    }

    fun openClaudeAiConnectors() {
        val intent = Intent(Intent.ACTION_VIEW, CLAUDE_AI_CONNECTORS_URL.toUri())
        context.startActivity(intent)
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        modifier = Modifier.testTag("mcp-sheet"),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                text = stringResource(R.string.settings_mcp),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )

            Text(
                text = stringResource(R.string.settings_mcp_explainer),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Text(
                text = stringResource(R.string.settings_mcp_endpoint_label),
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Row(
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
            ) {
                Text(
                    text = MCP_ENDPOINT_URL,
                    modifier = Modifier
                        .weight(1f)
                        .horizontalScroll(rememberScrollState()),
                    style = MaterialTheme.typography.bodyMedium,
                    fontFamily = FontFamily.Monospace,
                )
                OutlinedButton(
                    onClick = { copy("MCP endpoint", MCP_ENDPOINT_URL, "endpoint") },
                    contentPadding = PaddingValues(horizontal = 14.dp, vertical = 6.dp),
                    modifier = Modifier.testTag("mcp-copy-endpoint"),
                ) {
                    Text(
                        text = if (copiedField == "endpoint") {
                            stringResource(R.string.settings_mcp_copied)
                        } else {
                            stringResource(R.string.settings_mcp_copy_url)
                        },
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }

            HorizontalDivider()

            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
            ) {
                McpClient.entries.forEach { client ->
                    FilterChip(
                        selected = selectedClient == client,
                        onClick = { selectedClient = client },
                        label = { Text(stringResource(client.labelRes)) },
                        colors = FilterChipDefaults.filterChipColors(),
                    )
                }
            }

            Text(
                text = stringResource(selectedClient.stepsRes),
                style = MaterialTheme.typography.bodyMedium,
            )

            snippetFor(selectedClient)?.let { snippet ->
                Text(
                    text = snippet,
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                )
                OutlinedButton(
                    onClick = { copy("MCP snippet", snippet, "snippet") },
                    modifier = Modifier.testTag("mcp-copy-snippet"),
                ) {
                    Text(
                        text = if (copiedField == "snippet") {
                            stringResource(R.string.settings_mcp_copied)
                        } else {
                            stringResource(R.string.settings_mcp_copy_snippet)
                        },
                    )
                }
            }

            if (selectedClient == McpClient.ClaudeAI) {
                OutlinedButton(
                    onClick = ::openClaudeAiConnectors,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(stringResource(R.string.settings_mcp_open_claude))
                }
            }

            HorizontalDivider()

            Row(
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Button(
                    onClick = ::shareUrl,
                    modifier = Modifier
                        .weight(1f)
                        .testTag("mcp-share"),
                ) {
                    Text(stringResource(R.string.settings_mcp_share))
                }
                OutlinedButton(
                    onClick = {
                        scope.launch {
                            sheetState.hide()
                            onDismiss()
                        }
                    },
                ) {
                    Text("Close")
                }
            }
        }
    }
}
