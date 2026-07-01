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
        stepsEnglish: "Add WaiComputer as a remote MCP server, then approve the OAuth login in your browser — no token to copy. Your OpenClaw agent can ask and search your whole brain.",
        stepsRussian: "Добавь WaiComputer как удалённый MCP-сервер и подтверди вход через OAuth в браузере — токен копировать не нужно. Агент OpenClaw сможет спрашивать и искать по всему мозгу.",
        snippet: """
        openclaw mcp add waicomputer \\
          --url \(mcpEndpointURL) \\
          --transport streamable-http \\
          --auth oauth
        openclaw mcp login waicomputer
        """,
        externalLink: (
            englishLabel: "OpenClaw MCP docs",
            russianLabel: "Документация OpenClaw MCP",
            url: URL(string: "https://docs.openclaw.ai/cli/mcp")!
        )
    ),
    .hermes: McpClientGuide(
        stepsEnglish: "Add WaiComputer under mcp_servers in ~/.hermes/config.yaml, then run /reload-mcp. Approve the OAuth login on first connect.",
        stepsRussian: "Добавь WaiComputer в mcp_servers в ~/.hermes/config.yaml и выполни /reload-mcp. Подтверди OAuth-вход при первом подключении.",
        snippet: """
        # ~/.hermes/config.yaml
        mcp_servers:
          waicomputer:
            url: "\(mcpEndpointURL)"
            auth: oauth

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
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var client: McpClient = .openClaw
    @State private var copiedField: String?

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        Group {
            if horizontalSizeClass == .regular {
                regularLayout
            } else {
                compactForm
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

    private var compactForm: some View {
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
    }

    private var regularLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                regularHeader

                LazyVGrid(
                    columns: [GridItem(.adaptive(minimum: 320), spacing: Spacing.lg, alignment: .top)],
                    alignment: .leading,
                    spacing: Spacing.lg
                ) {
                    regularEndpointPanel
                    regularGuidePanel
                    regularAccessPanel
                }
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xxl)
            .frame(maxWidth: 920, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("settings-mcp-regular-layout")
    }

    private var regularHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Image(systemName: "link.circle")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 42, height: 42)
                .background(Color(uiColor: .secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("MCP")
                    .font(Typography.displayMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Connect agents to ask, search, and remember with your WaiComputer brain.",
                    "Подключи агентов к вопросам, поиску и запоминанию через WaiComputer."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            }
        }
        .accessibilityIdentifier("settings-mcp-regular-header")
    }

    private var regularEndpointPanel: some View {
        regularPanel(
            title: t("Endpoint", "Адрес"),
            subtitle: t(
                "Paste this URL into any remote MCP client that supports OAuth.",
                "Вставь этот адрес в любой remote MCP-клиент с OAuth."
            ),
            systemImage: "network",
            identifier: "settings-mcp-regular-endpoint-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                HStack(spacing: Spacing.sm) {
                    Text(mcpEndpointURL)
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textPrimary)
                        .textSelection(.enabled)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .padding(.horizontal, Spacing.sm)
                        .padding(.vertical, Spacing.xs)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(uiColor: .tertiarySystemGroupedBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

                    Button {
                        copy(mcpEndpointURL, field: "endpoint")
                    } label: {
                        Label(
                            copiedField == "endpoint" ? t("Copied", "Скопировано") : t("Copy", "Копировать"),
                            systemImage: copiedField == "endpoint" ? "checkmark" : "doc.on.doc"
                        )
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.regular)
                    .accessibilityIdentifier("settings-mcp-copy-endpoint")
                }

                Text(t(
                    "Your agent opens wai.computer for approval on first connect. No token is copied into the app.",
                    "При первом подключении агент откроет wai.computer для подтверждения. Токен не копируется в приложение."
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var regularGuidePanel: some View {
        regularPanel(
            title: t("Setup guide", "Инструкция"),
            subtitle: t(
                "Choose the client you are configuring.",
                "Выбери клиент, который настраиваешь."
            ),
            systemImage: "terminal",
            identifier: "settings-mcp-regular-guide-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                Picker(t("Client", "Клиент"), selection: $client) {
                    ForEach(McpClient.allCases) { value in
                        Text(value.rawValue).tag(value)
                    }
                }
                .pickerStyle(.menu)
                .accessibilityIdentifier("settings-mcp-client-picker")

                if let guide = mcpClientGuides[client] {
                    Text(t(guide.stepsEnglish, guide.stepsRussian))
                        .font(Typography.body)
                        .foregroundStyle(Palette.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)

                    if let snippet = guide.snippet {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            ScrollView(.horizontal, showsIndicators: false) {
                                Text(snippet)
                                    .font(Typography.mono)
                                    .foregroundStyle(Palette.textPrimary)
                                    .textSelection(.enabled)
                                    .padding(Spacing.sm)
                            }
                            .background(Color(uiColor: .tertiarySystemGroupedBackground))
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

                            Button {
                                copy(snippet, field: "snippet")
                            } label: {
                                Label(
                                    copiedField == "snippet" ? t("Copied", "Скопировано") : t("Copy snippet", "Скопировать фрагмент"),
                                    systemImage: copiedField == "snippet" ? "checkmark" : "doc.on.doc"
                                )
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.regular)
                            .accessibilityIdentifier("settings-mcp-copy-snippet")
                        }
                    }

                    if let link = guide.externalLink {
                        Link(destination: link.url) {
                            Label(t(link.englishLabel, link.russianLabel), systemImage: "arrow.up.right")
                        }
                        .font(Typography.body)
                    }
                }
            }
        }
    }

    private var regularAccessPanel: some View {
        regularPanel(
            title: t("Access", "Доступ"),
            subtitle: t(
                "Manage approvals and API tokens on the web dashboard.",
                "Управляй подтверждениями и API-токенами в веб-кабинете."
            ),
            systemImage: "lock.shield",
            identifier: "settings-mcp-regular-access-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                Text(t(
                    "Each agent is approved by name on wai.computer and can be revoked any time.",
                    "Каждый агент подтверждается по имени на wai.computer, и доступ можно отозвать в любой момент."
                ))
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

                Link(destination: waiComputerWebURL) {
                    Label(
                        t("Manage API tokens on wai.computer", "Управление API-токенами на wai.computer"),
                        systemImage: "safari"
                    )
                }
                .font(Typography.body)
                .accessibilityIdentifier("settings-mcp-manage-tokens")
            }
        }
    }

    private func regularPanel<Content: View>(
        title: String,
        subtitle: String?,
        systemImage: String,
        identifier: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .top, spacing: Spacing.md) {
                Image(systemName: systemImage)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.accent)
                    .frame(width: 30, height: 30)
                    .background(Palette.accentSubtle)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(title)
                        .font(Typography.headingLarge)
                        .foregroundStyle(Palette.textPrimary)
                    if let subtitle {
                        Text(subtitle)
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            Divider()
            content()
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
        .accessibilityIdentifier(identifier)
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
