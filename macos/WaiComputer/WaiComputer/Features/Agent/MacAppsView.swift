import SwiftUI
import WaiComputerKit

struct MacAppsView: View {
    let apiClient: APIClient

    @State private var apps: [UserApp] = []
    @State private var isLoading = false
    @State private var error: String?
    @State private var selectedApp: UserApp?

    var body: some View {
        VStack(spacing: 0) {
            if let app = selectedApp {
                AppDetailView(
                    app: app,
                    apiClient: apiClient,
                    onBack: { selectedApp = nil },
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
        .alert("Apps Error", isPresented: Binding(
            get: { error != nil },
            set: { if !$0 { error = nil } }
        )) {
            Button("OK") { error = nil }
        } message: {
            Text(error ?? "Something went wrong.")
        }
    }

    // MARK: - App Grid

    private var appGrid: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Apps")
                    .font(Typography.displaySmall)
                Spacer()
                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                }
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.md)

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

                    Text("Ask Wai to create one.")
                        .font(Typography.body)
                        .foregroundStyle(Palette.textTertiary)

                    Spacer()
                }
            } else {
                ScrollView {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 160, maximum: 200), spacing: Spacing.md)],
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

    // MARK: - Actions

    private func loadApps() async {
        isLoading = true
        do {
            apps = try await apiClient.listApps()
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }
}

// MARK: - App Card

private struct AppCard: View {
    let app: UserApp

    var body: some View {
        VStack(spacing: Spacing.md) {
            Text(app.icon ?? "📦")
                .font(.system(size: 32))

            Text(app.displayName)
                .font(Typography.headingMedium)
                .lineLimit(1)

            Text("\(app.itemCount) item\(app.itemCount == 1 ? "" : "s")")
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
        }
        .frame(maxWidth: .infinity)
        .padding(Spacing.lg)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
        .accessibilityIdentifier("app-card-\(app.id)")
    }
}

// MARK: - App Detail View

private struct AppDetailView: View {
    let app: UserApp
    let apiClient: APIClient
    let onBack: () -> Void
    let onDelete: () -> Void

    @State private var items: [AppItem] = []
    @State private var isLoading = false
    @State private var error: String?

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack(spacing: Spacing.md) {
                Button {
                    onBack()
                } label: {
                    Image(systemName: "chevron.left")
                        .font(Typography.headingSmall)
                        .foregroundStyle(Palette.accent)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("app-detail-back")

                Text(app.icon ?? "📦")
                    .font(.system(size: 22))

                Text(app.displayName)
                    .font(Typography.displaySmall)

                Spacer()

                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                }

                Button {
                    deleteApp()
                } label: {
                    Image(systemName: "trash")
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textTertiary)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("app-delete-\(app.id)")
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.md)

            WaiDivider()

            // Items list
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
                            AppItemRow(
                                item: item,
                                onDelete: { deleteItem(item) }
                            )
                        }
                    }
                    .padding(Spacing.lg)
                }
            }
        }
        .task {
            await loadItems()
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

    private func loadItems() async {
        isLoading = true
        do {
            items = try await apiClient.listAppItems(app.id)
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func deleteItem(_ item: AppItem) {
        Task {
            do {
                try await apiClient.deleteAppItem(app.id, itemId: item.id)
                items.removeAll { $0.id == item.id }
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func deleteApp() {
        Task {
            do {
                try await apiClient.deleteApp(app.id)
                onDelete()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

// MARK: - App Item Row

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

            Button {
                onDelete()
            } label: {
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
        case .string(let s):
            return s
        case .int(let i):
            return "\(i)"
        case .double(let d):
            return String(format: "%.2f", d)
        case .bool(let b):
            return b ? "Yes" : "No"
        case .null:
            return "-"
        case .array(let arr):
            return "[\(arr.count) items]"
        case .object(let obj):
            return "{\(obj.count) fields}"
        }
    }

    private func formatDate(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}
