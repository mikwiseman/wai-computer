import SwiftUI
import WaiComputerKit

/// Hermes-style "connect a source" screen: a categorized catalog of data MCPs
/// you flip on, plus an "Add custom MCP" escape hatch. WaiComputer becomes the
/// MCP CLIENT, pulling each source's data into the brain (read-only) and linking
/// it. Mirrors the macOS Sources surface, backed by the shared Kit catalog.
struct McpIngestionView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager

    @State private var catalog: SourceCatalog?
    @State private var connections: [McpIngestionConnection] = []
    @State private var loading = true
    @State private var error: String?
    @State private var depth = ""

    @State private var openEntryId: String?
    @State private var tileToken = ""

    @State private var showAddForm = false
    @State private var label = ""
    @State private var url = ""
    @State private var token = ""
    @State private var busy = false
    @State private var disconnecting: McpIngestionConnection?

    private static let icons: [String: String] = [
        "gmail": "envelope.fill", "telegram": "paperplane.fill",
        "slack": "bubble.left.and.bubble.right.fill", "notion": "doc.text.fill",
        "obsidian": "circle.hexagongrid.fill", "google_drive": "folder.fill",
        "google_calendar": "calendar", "wai_time": "clock.fill", "wai_money": "creditcard.fill",
    ]

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        List {
            if loading {
                ProgressView()
            } else {
                if !connections.isEmpty {
                    Section {
                        ForEach(connections) { connectedRow($0) }
                    } header: { Text(t("Connected", "Подключённые")) }
                }
                ForEach(catalog?.categories ?? []) { category in
                    let entries = (catalog?.entries ?? []).filter { $0.category == category.id }
                    if !entries.isEmpty {
                        Section {
                            ForEach(entries) { tileRow($0) }
                        } header: { Text(t(category.nameEn, category.nameRu)) }
                    }
                }
                if catalog?.customSupported == true {
                    Section {
                        DisclosureGroup(isExpanded: $showAddForm) { addForm } label: {
                            Text(t("Add custom MCP (advanced)", "Добавить свой MCP (для продвинутых)"))
                        }
                    }
                }
            }
            if let error {
                Text(error).font(Typography.bodySmall).foregroundStyle(.red)
            }
        }
        .navigationTitle(t("Sources", "Источники"))
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(
            t("Disconnect this source?", "Отключить источник?"),
            isPresented: Binding(get: { disconnecting != nil }, set: { if !$0 { disconnecting = nil } }),
            presenting: disconnecting
        ) { conn in
            Button(t("Disconnect", "Отключить"), role: .destructive) {
                Task { await remove(conn) }
            }
        } message: { _ in
            Text(t("Future syncs stop. Items already in your Brain stay.",
                   "Синхронизация остановится. Материалы в Мозге останутся."))
        }
        .task { await load() }
    }

    private func connectedRow(_ conn: McpIngestionConnection) -> some View {
        let s = statusText(conn)
        return VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: Self.icons[conn.sourceType ?? ""] ?? "link")
                    .foregroundStyle(Palette.accent).frame(width: 22)
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(conn.serverLabel).font(Typography.bodySmall.weight(.medium))
                    Text(s.text).font(Typography.labelSmall)
                        .foregroundStyle(s.danger ? .red : Palette.textTertiary)
                }
                Spacer()
            }
            HStack(spacing: Spacing.sm) {
                Spacer()
                Button(t("Sync", "Синхр.")) { Task { await sync(conn) } }
                    .buttonStyle(.bordered).controlSize(.small)
                Button(conn.enabled ? t("Pause", "Пауза") : t("Resume", "Возобновить")) {
                    Task { await toggle(conn) }
                }.buttonStyle(.bordered).controlSize(.small)
                Button(role: .destructive) { disconnecting = conn } label: {
                    Image(systemName: "trash")
                }.buttonStyle(.borderless)
            }
        }
        .padding(.vertical, Spacing.xxs)
    }

    private func tileRow(_ entry: SourceCatalogEntry) -> some View {
        let connected = connections.contains { $0.catalogId == entry.id }
        return VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: Self.icons[entry.id] ?? "link")
                    .foregroundStyle(Palette.accent).frame(width: 22)
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(entry.name).font(Typography.bodySmall.weight(.medium))
                    Text(t(entry.taglineEn, entry.taglineRu))
                        .font(Typography.labelSmall).foregroundStyle(Palette.textTertiary)
                }
                Spacer()
                if connected {
                    Text(t("Connected", "Подключено"))
                        .font(Typography.labelSmall.weight(.semibold)).foregroundStyle(Palette.accent)
                } else if !entry.isAvailable {
                    Text(t("Soon", "Скоро"))
                        .font(Typography.labelSmall.weight(.semibold)).foregroundStyle(Palette.textTertiary)
                } else {
                    Button(t("Connect", "Подключить")) {
                        if entry.authType == "pat" { openEntryId = entry.id; tileToken = "" }
                        else { Task { await connectTile(entry, authToken: nil) } }
                    }.buttonStyle(.borderedProminent).controlSize(.small).disabled(busy)
                }
            }
            if openEntryId == entry.id, entry.authType == "pat" {
                SecureField(t(entry.setupHintEn ?? "Access token", entry.setupHintRu ?? "Токен доступа"),
                            text: $tileToken)
                    .textFieldStyle(.roundedBorder).autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                HStack {
                    Button(t("Cancel", "Отмена")) { openEntryId = nil }.buttonStyle(.bordered).controlSize(.small)
                    Spacer()
                    Button(t("Connect", "Подключить")) {
                        Task { await connectTile(entry, authToken: tileToken.trimmingCharacters(in: .whitespaces)) }
                    }.buttonStyle(.borderedProminent).controlSize(.small)
                        .disabled(tileToken.trimmingCharacters(in: .whitespaces).isEmpty || busy)
                }
            }
        }
        .padding(.vertical, Spacing.xxs)
    }

    private var addForm: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            TextField(t("Source name", "Название"), text: $label)
                .textFieldStyle(.roundedBorder).autocorrectionDisabled()
            TextField("https://mcp.example.com/…", text: $url)
                .textFieldStyle(.roundedBorder).autocorrectionDisabled()
                .textInputAutocapitalization(.never).keyboardType(.URL)
            SecureField(t("Access token (optional)", "Токен доступа (опц.)"), text: $token)
                .textFieldStyle(.roundedBorder).autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            depthPicker
            HStack {
                Spacer()
                Button {
                    Task { await connectCustom() }
                } label: {
                    if busy { ProgressView() } else { Text(t("Connect", "Подключить")) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(busy || url.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(.vertical, Spacing.xs)
    }

    private var depthPicker: some View {
        Picker(t("History", "История"), selection: $depth) {
            ForEach(catalog?.backfillDepths ?? [], id: \.self) { d in
                Text(depthLabel(d)).tag(d)
            }
        }
        .pickerStyle(.menu)
    }

    private func depthLabel(_ d: String) -> String {
        switch d {
        case "recent_30d": return t("Recent 30 days", "Последние 30 дней")
        case "recent_90d": return t("Recent 90 days", "Последние 90 дней")
        case "last_year": return t("Last year", "Последний год")
        case "everything": return t("Everything", "Всё")
        default: return d
        }
    }

    private func statusText(_ c: McpIngestionConnection) -> (text: String, danger: Bool) {
        if ["error", "error_terminal", "needs_setup", "degraded"].contains(c.status) {
            return (t("Reconnect needed", "Нужно переподключить"), true)
        }
        let n = c.itemCount ?? 0
        if !c.enabled { return (t("Paused · \(n) items", "Пауза · \(n) материалов"), false) }
        if c.lastSyncAt == nil { return (t("Syncing…", "Синхронизация…"), false) }
        let ago = relativeAgo(c.secondsSinceSync)
        return (t("Synced \(n) · \(ago)", "Синхр. \(n) · \(ago)"), false)
    }

    private func relativeAgo(_ secs: Int?) -> String {
        guard let s = secs else { return "" }
        if s < 90 { return t("just now", "только что") }
        let m = s / 60
        if m < 90 { return t("\(m)m ago", "\(m) мин назад") }
        let h = m / 60
        if h < 36 { return t("\(h)h ago", "\(h) ч назад") }
        return t("\(h / 24)d ago", "\(h / 24) дн назад")
    }

    // MARK: - Actions

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let client = appState.getAPIClient()
            async let cat = client.getSourceCatalog()
            async let conns = client.listMcpIngestionConnections()
            let (c, l) = try await (cat, conns)
            catalog = c
            connections = l
            if depth.isEmpty { depth = c.defaultBackfillDepth }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func connectTile(_ entry: SourceCatalogEntry, authToken: String?) async {
        busy = true
        defer { busy = false }
        do {
            let created = try await appState.getAPIClient().connectMcpSource(
                catalogId: entry.id,
                authToken: (authToken?.isEmpty == true) ? nil : authToken,
                backfillDepth: depth.isEmpty ? nil : depth
            )
            openEntryId = nil
            try? await appState.getAPIClient().syncMcpIngestionConnection(id: created.id)
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func connectCustom() async {
        let trimmedToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        busy = true
        defer { busy = false }
        do {
            let created = try await appState.getAPIClient().createMcpIngestionConnection(
                serverLabel: label.trimmingCharacters(in: .whitespaces),
                serverUrl: url.trimmingCharacters(in: .whitespaces),
                authType: trimmedToken.isEmpty ? "none" : "pat",
                authToken: trimmedToken.isEmpty ? nil : trimmedToken,
                backfillDepth: depth.isEmpty ? nil : depth
            )
            label = ""; url = ""; token = ""; showAddForm = false
            try? await appState.getAPIClient().syncMcpIngestionConnection(id: created.id)
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func sync(_ conn: McpIngestionConnection) async {
        do { try await appState.getAPIClient().syncMcpIngestionConnection(id: conn.id) }
        catch { self.error = error.localizedDescription }
    }

    private func toggle(_ conn: McpIngestionConnection) async {
        do {
            _ = try await appState.getAPIClient().updateMcpIngestionConnection(id: conn.id, enabled: !conn.enabled)
            await load()
        } catch { self.error = error.localizedDescription }
    }

    private func remove(_ conn: McpIngestionConnection) async {
        do {
            try await appState.getAPIClient().deleteMcpIngestionConnection(id: conn.id)
            await load()
        } catch { self.error = error.localizedDescription }
    }
}
