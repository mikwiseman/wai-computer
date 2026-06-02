import SwiftUI
import WaiComputerKit

/// Settings screen to connect ANY third-party MCP server as an ingestion source
/// — WaiComputer pulls that server's data into the brain. Distinct from the
/// inbound connector instructions (McpConnectView), which connect external apps
/// TO Wai. Ported from macOS McpIngestionSection.
struct McpIngestionView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager

    @State private var connections: [McpIngestionConnection] = []
    @State private var loading = true
    @State private var error: String?

    @State private var showAddForm = false
    @State private var label = ""
    @State private var url = ""
    @State private var token = ""
    @State private var submitting = false

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        List {
            Section {
                if loading {
                    ProgressView()
                } else if connections.isEmpty && !showAddForm {
                    Text(t("No sources connected yet.", "Источники ещё не подключены."))
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                } else {
                    ForEach(connections) { connection in
                        connectionRow(connection)
                    }
                }

                if showAddForm {
                    addForm
                } else {
                    Button {
                        showAddForm = true
                    } label: {
                        Label(t("Connect a source", "Подключить источник"), systemImage: "plus")
                    }
                }

                if let error {
                    Text(error).font(Typography.bodySmall).foregroundStyle(.red)
                }
            } header: {
                Text(t("Connected sources", "Подключённые источники"))
            } footer: {
                Text(t(
                    "Connect any MCP server and WaiComputer pulls its content into your brain — searchable and summarized.",
                    "Подключите любой MCP-сервер, и WaiComputer добавит его материалы в вашу базу — с поиском и саммари."
                ))
            }
        }
        .navigationTitle(t("Data sources", "Источники данных"))
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func connectionRow(_ connection: McpIngestionConnection) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(connection.serverLabel).font(Typography.bodySmall.weight(.medium))
                Text(connection.serverUrl)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
                    .lineLimit(1)
                HStack(spacing: Spacing.xs) {
                    statusBadge(connection)
                    if let last = connection.lastError {
                        Text(last).font(Typography.labelSmall).foregroundStyle(.red)
                    }
                }
            }
            Spacer()
            Button(t("Sync", "Синхр.")) {
                Task { await sync(connection) }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            Button(role: .destructive) {
                Task { await remove(connection) }
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.borderless)
        }
        .padding(.vertical, Spacing.xxs)
    }

    private func statusBadge(_ connection: McpIngestionConnection) -> some View {
        let color: Color = connection.status == "error"
            ? .red
            : (connection.enabled ? Palette.accent : Palette.textTertiary)
        return Text(connection.status.uppercased())
            .font(Typography.labelSmall)
            .foregroundStyle(color)
    }

    private var addForm: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            TextField(t("Name (e.g. My Notes)", "Название (напр. Мои заметки)"), text: $label)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
            TextField("https://mcp.example.com/…", text: $url)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .keyboardType(.URL)
            TextField(t("Access token (optional)", "Токен доступа (опц.)"), text: $token)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            HStack {
                Button(t("Cancel", "Отмена")) { resetForm() }
                    .buttonStyle(.bordered)
                Spacer()
                Button {
                    Task { await submit() }
                } label: {
                    if submitting {
                        ProgressView()
                    } else {
                        Text(t("Connect", "Подключить"))
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(submitting || label.trimmingCharacters(in: .whitespaces).isEmpty
                          || url.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(.vertical, Spacing.xs)
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            connections = try await appState.getAPIClient().listMcpIngestionConnections()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func submit() async {
        let trimmedToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        submitting = true
        defer { submitting = false }
        do {
            _ = try await appState.getAPIClient().createMcpIngestionConnection(
                serverLabel: label.trimmingCharacters(in: .whitespaces),
                serverUrl: url.trimmingCharacters(in: .whitespaces),
                authType: trimmedToken.isEmpty ? "none" : "pat",
                authToken: trimmedToken.isEmpty ? nil : trimmedToken
            )
            resetForm()
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func sync(_ connection: McpIngestionConnection) async {
        do {
            try await appState.getAPIClient().syncMcpIngestionConnection(id: connection.id)
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func remove(_ connection: McpIngestionConnection) async {
        do {
            try await appState.getAPIClient().deleteMcpIngestionConnection(id: connection.id)
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func resetForm() {
        showAddForm = false
        label = ""
        url = ""
        token = ""
        error = nil
    }
}
