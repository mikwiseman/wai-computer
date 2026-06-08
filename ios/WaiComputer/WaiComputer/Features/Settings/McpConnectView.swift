import SwiftUI
import UIKit
import WaiComputerKit

private let mcpEndpointURL = "https://wai.computer/mcp"
private let waiComputerWebURL = URL(string: "https://wai.computer")!

private enum McpClient: String, CaseIterable, Identifiable {
    case openClaw = "OpenClaw"
    case hermes = "Hermes"
    case claudeAI = "Claude.ai"
    case cursor = "Cursor"
    case chatGPT = "ChatGPT"
    case claudeCode = "Claude Code"
    case codex = "Codex CLI"

    var id: String { rawValue }
}

private struct McpClientGuide {
    let stepsEnglish: String
    let stepsRussian: String
    let snippet: String?
    let externalLink: (englishLabel: String, russianLabel: String, url: URL)?
}

private let mcpClientGuides: [McpClient: McpClientGuide] = [
    .openClaw: McpClientGuide(
        stepsEnglish: "Add WaiComputer as a remote MCP server, then approve the OAuth login in your browser — no token to copy. Your OpenClaw agent can ask and search your whole brain. To let it remember new facts too, create a write-enabled token under API tokens on the web dashboard (wai.computer) and use the header form.",
        stepsRussian: "Добавь WaiComputer как удалённый MCP-сервер и подтверди вход через OAuth в браузере — токен копировать не нужно. Агент OpenClaw сможет спрашивать и искать по всему мозгу. Чтобы он мог запоминать факты, создай токен с правом записи в разделе API-токены в веб-кабинете (wai.computer) и используй форму с заголовком.",
        snippet: """
        # Recall your brain (OAuth — approve in your browser):
        openclaw mcp add waicomputer \\
          --url \(mcpEndpointURL) \\
          --transport streamable-http \\
          --auth oauth
        openclaw mcp login waicomputer

        # Memory bank (read + write) — use a write-enabled token instead:
        openclaw mcp add waicomputer \\
          --url \(mcpEndpointURL) \\
          --transport streamable-http \\
          --header "Authorization: Bearer wc_live_…"
        """,
        externalLink: (
            englishLabel: "OpenClaw MCP docs",
            russianLabel: "Документация OpenClaw MCP",
            url: URL(string: "https://docs.openclaw.ai/cli/mcp")!
        )
    ),
    .hermes: McpClientGuide(
        stepsEnglish: "Add WaiComputer under mcp_servers in ~/.hermes/config.yaml, then run /reload-mcp. Approve the OAuth login on first connect. For a memory bank (read + write), create a write-enabled token under API tokens on the web dashboard (wai.computer) and use the headers form instead.",
        stepsRussian: "Добавь WaiComputer в mcp_servers в ~/.hermes/config.yaml и выполни /reload-mcp. Подтверди OAuth-вход при первом подключении. Для банка памяти (чтение + запись) создай токен с правом записи в разделе API-токены в веб-кабинете (wai.computer) и используй форму с headers.",
        snippet: """
        # ~/.hermes/config.yaml — recall your brain (OAuth, approve in browser):
        mcp_servers:
          waicomputer:
            url: "\(mcpEndpointURL)"
            auth: oauth

        # Memory bank (read + write) — use a write-enabled token instead:
        mcp_servers:
          waicomputer:
            url: "\(mcpEndpointURL)"
            headers:
              Authorization: "Bearer wc_live_…"

        # then in Hermes:  /reload-mcp
        """,
        externalLink: (
            englishLabel: "Hermes MCP docs",
            russianLabel: "Документация Hermes MCP",
            url: URL(string: "https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp")!
        )
    ),
    .claudeAI: McpClientGuide(
        stepsEnglish: "Open Customize → Connectors and tap the “+” button, paste the URL, then approve the request on wai.computer when prompted.",
        stepsRussian: "Открой «Настроить → Коннекторы», нажми «+», вставь URL и подтверди запрос на wai.computer.",
        snippet: nil,
        externalLink: (
            englishLabel: "Open Connectors in Claude.ai",
            russianLabel: "Открыть «Коннекторы» в Claude.ai",
            url: URL(string: "https://claude.ai/customize/connectors")!
        )
    ),
    .cursor: McpClientGuide(
        stepsEnglish: "Add this server to .cursor/mcp.json in your project root (or to your global Cursor MCP settings). Cursor starts the OAuth flow on first use.",
        stepsRussian: "Добавь этот сервер в .cursor/mcp.json в корне проекта (или в глобальные MCP-настройки Cursor). OAuth начнётся при первом использовании.",
        snippet: """
        {
          "mcpServers": {
            "waicomputer": {
              "url": "\(mcpEndpointURL)"
            }
          }
        }
        """,
        externalLink: nil
    ),
    .chatGPT: McpClientGuide(
        stepsEnglish: "Open ChatGPT → Settings → Connectors. Enable Developer Mode, add an MCP server, and paste the URL.",
        stepsRussian: "Открой ChatGPT → Settings → Connectors. Включи Developer Mode, добавь MCP-сервер и вставь URL.",
        snippet: nil,
        externalLink: nil
    ),
    .claudeCode: McpClientGuide(
        stepsEnglish: "Either run the CLI add command, or drop the snippet into a .mcp.json at your project root.",
        stepsRussian: "Запусти CLI-команду или положи сниппет в .mcp.json в корне проекта.",
        snippet: """
        # CLI
        claude mcp add waicomputer \(mcpEndpointURL)

        # Or .mcp.json:
        {
          "mcpServers": {
            "waicomputer": {
              "type": "http",
              "url": "\(mcpEndpointURL)"
            }
          }
        }
        """,
        externalLink: nil
    ),
    .codex: McpClientGuide(
        stepsEnglish: "Add the server, then complete the OAuth login from the browser when prompted.",
        stepsRussian: "Добавь сервер, затем заверши OAuth-вход в браузере, когда Codex попросит.",
        snippet: """
        codex mcp add waicomputer --url \(mcpEndpointURL)
        codex mcp login waicomputer
        """,
        externalLink: nil
    ),
]

struct McpConnectView: View {
    @EnvironmentObject var languageManager: LanguageManager
    @State private var client: McpClient = .openClaw
    @State private var copiedField: String?

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        Form {
            Section {
                HStack {
                    Text(mcpEndpointURL)
                        .font(.system(.body, design: .monospaced))
                        .textSelection(.enabled)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer()
                    Button(copiedField == "endpoint" ? t("Copied", "Скопировано") : t("Copy", "Копировать")) {
                        copy(mcpEndpointURL, field: "endpoint")
                    }
                    .accessibilityIdentifier("settings-mcp-copy-endpoint")
                }
            } header: {
                Text(t("Endpoint", "Адрес"))
            } footer: {
                Text(t(
                    "Give your AI agent a brain. WaiComputer exposes an MCP (Model Context Protocol) server, so any agent — OpenClaw, Hermes, Claude, Cursor, … — can recall everything you've captured (ask your brain a cited question, search recordings, notes, and chats) and, if you allow it, remember new facts back. You approve each agent by name on wai.computer and can revoke any time.",
                    "Дай своему ИИ-агенту память. WaiComputer работает как MCP-сервер (Model Context Protocol), поэтому любой агент — OpenClaw, Hermes, Claude, Cursor, … — может вспоминать всё, что ты сохранил (задать вопрос мозгу с цитатами, искать по записям, заметкам и чатам) и, если разрешишь, запоминать новые факты. Каждого агента ты подтверждаешь по имени на wai.computer и можешь отозвать доступ в любой момент."
                ))
            }

            Section {
                Picker(t("Client", "Клиент"), selection: $client) {
                    ForEach(McpClient.allCases) { value in
                        Text(value.rawValue).tag(value)
                    }
                }
                .pickerStyle(.menu)
                .accessibilityIdentifier("settings-mcp-client-picker")
            } header: {
                Text(t("Setup guide", "Инструкция"))
            }

            if let guide = mcpClientGuides[client] {
                Section {
                    Text(t(guide.stepsEnglish, guide.stepsRussian))
                        .fixedSize(horizontal: false, vertical: true)

                    if let snippet = guide.snippet {
                        ScrollView(.horizontal, showsIndicators: false) {
                            Text(snippet)
                                .font(.system(.callout, design: .monospaced))
                                .textSelection(.enabled)
                                .padding(.vertical, 4)
                        }

                        Button(copiedField == "snippet" ? t("Copied", "Скопировано") : t("Copy snippet", "Скопировать фрагмент")) {
                            copy(snippet, field: "snippet")
                        }
                        .accessibilityIdentifier("settings-mcp-copy-snippet")
                    }

                    if let link = guide.externalLink {
                        Link(t(link.englishLabel, link.russianLabel), destination: link.url)
                    }

                    // The native apps don't manage API tokens — link out to the web
                    // dashboard so the write-token instruction isn't a dead end.
                    Link(
                        t("Manage API tokens on wai.computer", "Управление API-токенами на wai.computer"),
                        destination: waiComputerWebURL
                    )
                    .accessibilityIdentifier("settings-mcp-manage-tokens")
                }
            }
        }
        .navigationTitle("MCP")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if let url = URL(string: mcpEndpointURL) {
                    ShareLink(item: url) {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .accessibilityIdentifier("settings-mcp-share")
                }
            }
        }
    }

    private func copy(_ value: String, field: String) {
        UIPasteboard.general.string = value
        copiedField = field
        Task {
            try? await Task.sleep(for: .seconds(1.5))
            if copiedField == field {
                copiedField = nil
            }
        }
    }
}

#Preview {
    NavigationStack {
        McpConnectView()
            .environmentObject(LanguageManager.shared)
    }
}
