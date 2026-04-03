import SwiftUI
import WaiComputerKit

struct MacAppsView: View {
    let apiClient: APIClient

    @State private var apps: [UserApp] = []
    @State private var isLoading = false
    @State private var error: String?
    @State private var selectedApp: UserApp?
    @State private var newAppName = ""
    @State private var newAppDescription = ""
    @State private var newAppVisibility: AppVisibility = .private
    @State private var isCreating = false
    @State private var statusFilter: AppStatusFilter = .all
    @State private var visibilityFilter: AppVisibilityFilter = .all

    var body: some View {
        VStack(spacing: 0) {
            if let app = selectedApp {
                AppDetailView(
                    app: app,
                    apiClient: apiClient,
                    onBack: { selectedApp = nil },
                    onUpdated: { updated in
                        replaceApp(updated)
                        selectedApp = updated
                    },
                    onDelete: {
                        apps.removeAll { $0.id == app.id }
                        selectedApp = nil
                    }
                )
            } else {
                appGrid
            }
        }
        .task {
            await loadApps()
        }
        .onChange(of: statusFilter) { _, _ in
            Task { await loadApps() }
        }
        .onChange(of: visibilityFilter) { _, _ in
            Task { await loadApps() }
        }
        .alert("Apps Error", isPresented: Binding(
            get: { error != nil },
            set: { if !$0 { error = nil } }
        )) {
            Button("OK") { error = nil }
        } message: {
            Text(error ?? "Something went wrong.")
        }
    }

    private var appGrid: some View {
        VStack(spacing: 0) {
            header
            createForm
            WaiDivider()

            if apps.isEmpty && !isLoading {
                VStack(spacing: Spacing.md) {
                    Spacer()

                    Image(systemName: "square.grid.2x2")
                        .font(.system(size: Spacing.xxxl))
                        .foregroundStyle(Palette.textTertiary)

                    Text("No apps yet")
                        .font(Typography.displaySmall)
                        .foregroundStyle(Palette.textSecondary)

                    Text("Create a draft, then publish it once Wai has generated the right experience.")
                        .font(Typography.body)
                        .foregroundStyle(Palette.textTertiary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 420)

                    Spacer()
                }
            } else {
                ScrollView {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 220, maximum: 280), spacing: Spacing.md)],
                        spacing: Spacing.md
                    ) {
                        ForEach(apps) { app in
                            AppCard(app: app)
                                .onTapGesture {
                                    selectedApp = app
                                }
                        }
                    }
                    .padding(Spacing.lg)
                }
            }
        }
    }

    private var header: some View {
        VStack(spacing: Spacing.sm) {
            HStack {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text("Apps")
                        .font(Typography.displaySmall)
                    Text("User-created products with lifecycle, sharing, and persistent data.")
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textTertiary)
                }

                Spacer()

                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            HStack(spacing: Spacing.md) {
                Picker("Status", selection: $statusFilter) {
                    ForEach(AppStatusFilter.allCases) { filter in
                        Text(filter.label).tag(filter)
                    }
                }
                .pickerStyle(.segmented)

                Picker("Visibility", selection: $visibilityFilter) {
                    ForEach(AppVisibilityFilter.allCases) { filter in
                        Text(filter.label).tag(filter)
                    }
                }
                .pickerStyle(.segmented)
            }
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.md)
    }

    private var createForm: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Text("NEW APP")
                .waiSectionHeader()

            TextField("App name (e.g. habits, deals, clients)...", text: $newAppName)
                .textFieldStyle(.roundedBorder)
                .font(Typography.body)
                .onSubmit { Task { await createApp() } }

            TextField("What this app is for", text: $newAppDescription, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .font(Typography.body)
                .lineLimit(1...3)

            HStack(spacing: Spacing.md) {
                Picker("Visibility", selection: $newAppVisibility) {
                    ForEach(AppVisibility.allCases, id: \.self) { visibility in
                        Text(visibility.label).tag(visibility)
                    }
                }
                .pickerStyle(.segmented)

                Button {
                    Task { await createApp() }
                } label: {
                    if isCreating {
                        ProgressView()
                            .controlSize(.small)
                            .frame(width: 100)
                    } else {
                        Text("Create Draft")
                            .font(Typography.headingSmall)
                            .frame(width: 100)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(newAppName.trimmed().isEmpty || isCreating)
            }
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.bottom, Spacing.md)
    }

    private func loadApps() async {
        isLoading = true
        defer { isLoading = false }

        do {
            apps = try await apiClient.listApps(
                status: statusFilter.value,
                visibility: visibilityFilter.value
            )
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }

    private func createApp() async {
        let name = newAppName.trimmed()
        guard !name.isEmpty else { return }

        isCreating = true
        defer { isCreating = false }

        do {
            let slug = name.lowercased()
                .replacingOccurrences(of: " ", with: "-")
                .filter { $0.isLetter || $0.isNumber || $0 == "-" }
            let created = try await apiClient.createApp(
                name: slug,
                displayName: name,
                description: newAppDescription.trimmed().nilIfEmpty,
                visibility: newAppVisibility
            )
            newAppName = ""
            newAppDescription = ""
            newAppVisibility = .private
            apps.insert(created, at: 0)
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }

    private func replaceApp(_ updated: UserApp) {
        if let index = apps.firstIndex(where: { $0.id == updated.id }) {
            apps[index] = updated
        } else {
            apps.insert(updated, at: 0)
        }
    }
}

private struct AppCard: View {
    let app: UserApp

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .top) {
                Text(app.icon ?? "📦")
                    .font(.system(size: 28))

                Spacer()

                VStack(alignment: .trailing, spacing: Spacing.xxs) {
                    badge(app.status.label, color: app.status.badgeColor)
                    badge(app.visibility.label, color: Palette.textTertiary)
                }
            }

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(app.displayName)
                    .font(Typography.headingMedium)
                    .lineLimit(1)

                if let description = app.description, !description.isEmpty {
                    Text(description)
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(2)
                } else {
                    Text("No description yet")
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textTertiary)
                        .italic()
                }
            }

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("\(app.itemCount) item\(app.itemCount == 1 ? "" : "s")")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)

                if let publishedAt = app.publishedAt {
                    Text("Published \(relativeDate(publishedAt))")
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                } else if let lastUsedAt = app.lastUsedAt {
                    Text("Used \(relativeDate(lastUsedAt))")
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                } else {
                    Text("Draft app")
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                }
            }

            if app.appUrl != nil {
                HStack(spacing: Spacing.xs) {
                    Image(systemName: "arrow.up.right.square")
                        .font(Typography.caption)
                    Text("Shareable")
                        .font(Typography.caption)
                }
                .foregroundStyle(Palette.accent)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.lg)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
        .accessibilityIdentifier("app-card-\(app.id)")
    }

    private func badge(_ text: String, color: Color) -> some View {
        Text(text.uppercased())
            .font(Typography.caption)
            .foregroundStyle(.white)
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, Spacing.xxs)
            .background(color)
            .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private func relativeDate(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

private struct AppDetailView: View {
    let apiClient: APIClient
    let onBack: () -> Void
    let onUpdated: (UserApp) -> Void
    let onDelete: () -> Void

    @State private var currentApp: UserApp
    @State private var items: [AppItem] = []
    @State private var isLoading = false
    @State private var isPublishing = false
    @State private var error: String?

    init(
        app: UserApp,
        apiClient: APIClient,
        onBack: @escaping () -> Void,
        onUpdated: @escaping (UserApp) -> Void,
        onDelete: @escaping () -> Void
    ) {
        self.apiClient = apiClient
        self.onBack = onBack
        self.onUpdated = onUpdated
        self.onDelete = onDelete
        _currentApp = State(initialValue: app)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            WaiDivider()

            if items.isEmpty && !isLoading {
                VStack(spacing: Spacing.md) {
                    Spacer()

                    ContentUnavailableView(
                        "No Items",
                        systemImage: "tray",
                        description: Text("This app has no items yet.")
                    )

                    Spacer()
                }
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: Spacing.md) {
                        ForEach(items) { item in
                            AppItemRow(item: item, onDelete: { deleteItem(item) })
                        }
                    }
                    .padding(Spacing.lg)
                }
            }
        }
        .task {
            await refresh()
        }
        .alert("App Error", isPresented: Binding(
            get: { error != nil },
            set: { if !$0 { error = nil } }
        )) {
            Button("OK") { error = nil }
        } message: {
            Text(error ?? "Something went wrong.")
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(spacing: Spacing.md) {
                Button(action: onBack) {
                    Image(systemName: "chevron.left")
                        .font(Typography.headingSmall)
                        .foregroundStyle(Palette.accent)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("app-detail-back")

                Text(currentApp.icon ?? "📦")
                    .font(.system(size: 22))

                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(currentApp.displayName)
                        .font(Typography.displaySmall)
                    Text("\(items.count) live item\(items.count == 1 ? "" : "s")")
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                }

                Spacer()

                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                }

                if let appUrl = currentApp.appUrl, let url = URL(string: appUrl) {
                    Link(destination: url) {
                        Label("Open", systemImage: "arrow.up.right.square")
                    }
                    .buttonStyle(.bordered)
                }

                Menu {
                    ForEach(AppVisibility.allCases, id: \.self) { visibility in
                        Button(visibility.label) {
                            updateVisibility(visibility)
                        }
                    }
                } label: {
                    Label(currentApp.visibility.label, systemImage: "eye")
                }
                .buttonStyle(.bordered)

                Button(action: { Task { await publishApp() } }) {
                    if isPublishing {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Text(currentApp.status == .live ? "Republish" : "Publish")
                    }
                }
                .buttonStyle(.borderedProminent)

                Button(action: addItem) {
                    Image(systemName: "plus")
                        .font(Typography.headingSmall)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Palette.accent)
                .help("Add item")

                Button(action: deleteApp) {
                    Image(systemName: "trash")
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textTertiary)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("app-delete-\(currentApp.id)")
            }

            VStack(alignment: .leading, spacing: Spacing.sm) {
                HStack(spacing: Spacing.sm) {
                    statusBadge(currentApp.status.label, color: currentApp.status.badgeColor)
                    statusBadge(currentApp.visibility.label, color: Palette.textTertiary)
                }

                if let description = currentApp.description, !description.isEmpty {
                    Text(description)
                        .font(Typography.body)
                        .foregroundStyle(Palette.textSecondary)
                }

                HStack(spacing: Spacing.md) {
                    Text("Created \(relativeDate(currentApp.createdAt))")
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)

                    if let lastUsedAt = currentApp.lastUsedAt {
                        Text("Used \(relativeDate(lastUsedAt))")
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textTertiary)
                    }

                    if let publishedAt = currentApp.publishedAt {
                        Text("Published \(relativeDate(publishedAt))")
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textTertiary)
                    }
                }
            }
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.md)
    }

    private func refresh() async {
        isLoading = true
        defer { isLoading = false }

        do {
            async let appTask = apiClient.getApp(currentApp.id)
            async let itemsTask = apiClient.listAppItems(currentApp.id)
            let (app, loadedItems) = try await (appTask, itemsTask)
            currentApp = app
            items = loadedItems
            onUpdated(app)
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }

    private func publishApp() async {
        isPublishing = true
        defer { isPublishing = false }

        do {
            let published = try await apiClient.publishApp(
                currentApp.id,
                visibility: currentApp.visibility,
                appUrl: currentApp.appUrl
            )
            currentApp = published
            onUpdated(published)
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }

    private func updateVisibility(_ visibility: AppVisibility) {
        Task {
            do {
                let updated = try await apiClient.updateApp(
                    currentApp.id,
                    visibility: visibility
                )
                currentApp = updated
                onUpdated(updated)
            } catch {
                self.error = error.userFacingMessage(context: .generic)
            }
        }
    }

    private func deleteItem(_ item: AppItem) {
        Task {
            do {
                try await apiClient.deleteAppItem(currentApp.id, itemId: item.id)
                items.removeAll { $0.id == item.id }
                await refresh()
            } catch {
                self.error = error.userFacingMessage(context: .generic)
            }
        }
    }

    private func addItem() {
        Task {
            do {
                let newData: [String: JSONValue] = [
                    "note": .string("New item"),
                    "created": .string(ISO8601DateFormatter().string(from: Date())),
                ]
                _ = try await apiClient.createAppItem(currentApp.id, data: newData)
                await refresh()
            } catch {
                self.error = error.userFacingMessage(context: .generic)
            }
        }
    }

    private func deleteApp() {
        Task {
            do {
                try await apiClient.deleteApp(currentApp.id)
                onDelete()
            } catch {
                self.error = error.userFacingMessage(context: .generic)
            }
        }
    }

    private func statusBadge(_ text: String, color: Color) -> some View {
        Text(text.uppercased())
            .font(Typography.caption)
            .foregroundStyle(.white)
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, Spacing.xxs)
            .background(color)
            .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private func relativeDate(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

private struct AppItemRow: View {
    let item: AppItem
    let onDelete: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                ForEach(sortedKeys, id: \.self) { key in
                    HStack(alignment: .top, spacing: Spacing.sm) {
                        Text(key)
                            .font(Typography.label)
                            .foregroundStyle(Palette.textTertiary)
                            .frame(width: 100, alignment: .trailing)

                        Text(formatValue(item.data[key]))
                            .font(Typography.body)
                            .textSelection(.enabled)
                    }
                }

                Text(formatDate(item.createdAt))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                    .padding(.top, Spacing.xxs)
            }

            Spacer()

            Button(action: onDelete) {
                Image(systemName: "trash")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
            .buttonStyle(.plain)
        }
        .waiCard()
    }

    private var sortedKeys: [String] {
        item.data.keys.sorted()
    }

    private func formatValue(_ value: JSONValue?) -> String {
        guard let value = value else { return "-" }
        switch value {
        case .string(let string):
            return string
        case .int(let int):
            return "\(int)"
        case .double(let double):
            return String(format: "%.2f", double)
        case .bool(let bool):
            return bool ? "Yes" : "No"
        case .null:
            return "-"
        case .array(let array):
            return "[\(array.count) items]"
        case .object(let object):
            return "{\(object.count) fields}"
        }
    }

    private func formatDate(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

private enum AppStatusFilter: String, CaseIterable, Identifiable {
    case all
    case draft
    case live
    case archived

    var id: String { rawValue }

    var label: String {
        switch self {
        case .all: return "All"
        case .draft: return "Draft"
        case .live: return "Live"
        case .archived: return "Archived"
        }
    }

    var value: AppStatus? {
        switch self {
        case .all: return nil
        case .draft: return .draft
        case .live: return .live
        case .archived: return .archived
        }
    }
}

private enum AppVisibilityFilter: String, CaseIterable, Identifiable {
    case all
    case `private`
    case unlisted
    case `public`

    var id: String { rawValue }

    var label: String {
        switch self {
        case .all: return "All"
        case .private: return "Private"
        case .unlisted: return "Unlisted"
        case .public: return "Public"
        }
    }

    var value: AppVisibility? {
        switch self {
        case .all: return nil
        case .private: return .private
        case .unlisted: return .unlisted
        case .public: return .public
        }
    }
}

private extension AppStatus {
    var label: String {
        switch self {
        case .draft: return "Draft"
        case .live: return "Live"
        case .archived: return "Archived"
        }
    }

    var badgeColor: Color {
        switch self {
        case .draft:
            return Palette.textTertiary
        case .live:
            return Palette.accent
        case .archived:
            return Palette.typeReflection
        }
    }
}

private extension AppVisibility {
    var label: String {
        switch self {
        case .private: return "Private"
        case .unlisted: return "Unlisted"
        case .public: return "Public"
        }
    }
}

private extension String {
    func trimmed() -> String {
        trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var nilIfEmpty: String? {
        let value = trimmed()
        return value.isEmpty ? nil : value
    }
}
