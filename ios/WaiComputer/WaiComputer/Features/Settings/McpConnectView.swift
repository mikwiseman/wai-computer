import SwiftUI
import UIKit

private let mcpEndpointURL = "https://wai.computer/mcp"

private enum McpClient: String, CaseIterable, Identifiable {
    case claudeAI = "Claude.ai"
    case cursor = "Cursor"
    case chatGPT = "ChatGPT"
    case claudeCode = "Claude Code"
    case codex = "Codex CLI"

    var id: String { rawValue }
}

private struct McpClientGuide {
    let steps: String
    let snippet: String?
    let externalLink: (label: String, url: URL)?
}

private let mcpClientGuides: [McpClient: McpClientGuide] = [
    .claudeAI: McpClientGuide(
        steps: "Open Customize → Connectors and tap the “+” button, paste the URL, then approve the request on wai.computer when prompted.",
        snippet: nil,
        externalLink: (
            label: "Open Connectors in Claude.ai",
            url: URL(string: "https://claude.ai/customize/connectors")!
        )
    ),
    .cursor: McpClientGuide(
        steps: "Add this server to .cursor/mcp.json in your project root (or to your global Cursor MCP settings). Cursor starts the OAuth flow on first use.",
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
        steps: "Open ChatGPT → Settings → Connectors. Enable Developer Mode, add an MCP server, and paste the URL.",
        snippet: nil,
        externalLink: nil
    ),
    .claudeCode: McpClientGuide(
        steps: "Either run the CLI add command, or drop the snippet into a .mcp.json at your project root.",
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
        steps: "Add the server, then complete the OAuth login from the browser when prompted.",
        snippet: """
        codex mcp add waicomputer --url \(mcpEndpointURL)
        codex mcp login waicomputer
        """,
        externalLink: nil
    ),
]

struct McpConnectView: View {
    @State private var client: McpClient = .claudeAI
    @State private var copiedField: String?

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
                    Button(copiedField == "endpoint" ? "Copied" : "Copy") {
                        copy(mcpEndpointURL, field: "endpoint")
                    }
                    .accessibilityIdentifier("settings-mcp-copy-endpoint")
                }
            } header: {
                Text("Endpoint")
            } footer: {
                Text("WaiComputer exposes an MCP (Model Context Protocol) server. Connect any MCP-compatible AI assistant to give it read-only access to your recordings, transcripts, summaries, action items, and metadata. You approve each client by name on wai.computer and can revoke any time from the client itself.")
            }

            Section {
                Picker("Client", selection: $client) {
                    ForEach(McpClient.allCases) { value in
                        Text(value.rawValue).tag(value)
                    }
                }
                .pickerStyle(.menu)
                .accessibilityIdentifier("settings-mcp-client-picker")
            } header: {
                Text("Setup guide")
            }

            if let guide = mcpClientGuides[client] {
                Section {
                    Text(guide.steps)
                        .fixedSize(horizontal: false, vertical: true)

                    if let snippet = guide.snippet {
                        ScrollView(.horizontal, showsIndicators: false) {
                            Text(snippet)
                                .font(.system(.callout, design: .monospaced))
                                .textSelection(.enabled)
                                .padding(.vertical, 4)
                        }

                        Button(copiedField == "snippet" ? "Copied" : "Copy snippet") {
                            copy(snippet, field: "snippet")
                        }
                        .accessibilityIdentifier("settings-mcp-copy-snippet")
                    }

                    if let link = guide.externalLink {
                        Link(link.label, destination: link.url)
                    }
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
    }
}
