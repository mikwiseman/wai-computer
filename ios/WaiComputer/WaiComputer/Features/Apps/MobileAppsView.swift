import SwiftUI
import WaiComputerKit

struct MobileAppsView: View {
    @EnvironmentObject private var appState: AppState

    @State private var apps: [UserApp] = []
    @State private var selectedApp: UserApp?
    @State private var isLoading = false
    @State private var error: String?
    @State private var newAppName = ""
    @State private var newAppDescription = ""

    var body: some View {
        NavigationStack {
            List {
                Section("Create App") {
                    TextField("App name", text: $newAppName)
                    TextField("Description", text: $newAppDescription, axis: .vertical)
                        .lineLimit(1...3)

                    Button("Create Draft") {
                        Task { await createApp() }
                    }
                    .disabled(newAppName.trimmed().isEmpty)
                }

                if apps.isEmpty && !isLoading {
                    Section {
                        ContentUnavailableView(
                            "No Apps",
                            systemImage: "square.grid.2x2",
                            description: Text("Ask Wai to build an app, then keep it here in your shelf.")
                        )
                    }
                } else {
                    Section("Your Apps") {
                        ForEach(apps) { app in
                            Button {
                                selectedApp = app
                            } label: {
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack {
                                        Text("\(app.icon ?? "📦") \(app.displayName)")
                                            .font(.headline)
                                        Spacer()
                                        Text(app.status.rawValue.capitalized)
                                            .font(.caption.weight(.medium))
                                            .foregroundStyle(.secondary)
                                    }

                                    if let description = app.description, !description.isEmpty {
                                        Text(description)
                                            .font(.subheadline)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(2)
                                    }

                                    HStack {
                                        Text(app.visibility.rawValue.capitalized)
                                        Text("•")
                                        Text("\(app.itemCount) items")
                                    }
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .navigationTitle("Apps")
            .overlay {
                if isLoading && apps.isEmpty {
                    ProgressView("Loading apps…")
                }
            }
            .task { await loadApps() }
            .refreshable { await loadApps() }
            .sheet(item: $selectedApp) { app in
                MobileAppDetailView(app: app)
                    .environmentObject(appState)
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
    }

    private func loadApps() async {
        isLoading = true
        defer { isLoading = false }

        do {
            apps = try await appState.getAPIClient().listApps()
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }

    private func createApp() async {
        let name = newAppName.trimmed()
        guard !name.isEmpty else { return }

        do {
            let slug = name.lowercased()
                .replacingOccurrences(of: " ", with: "-")
                .filter { $0.isLetter || $0.isNumber || $0 == "-" }
            let created = try await appState.getAPIClient().createApp(
                name: slug,
                displayName: name,
                description: newAppDescription.trimmed().nilIfEmpty
            )
            apps.insert(created, at: 0)
            newAppName = ""
            newAppDescription = ""
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }
}

private struct MobileAppDetailView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var appState: AppState

    @State private var app: UserApp
    @State private var items: [AppItem] = []
    @State private var error: String?

    init(app: UserApp) {
        _app = State(initialValue: app)
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(app.displayName)
                            .font(.title3.weight(.semibold))
                        if let description = app.description, !description.isEmpty {
                            Text(description)
                                .foregroundStyle(.secondary)
                        }
                        HStack {
                            Text(app.status.rawValue.capitalized)
                            Text("•")
                            Text(app.visibility.rawValue.capitalized)
                            if let publishedAt = app.publishedAt {
                                Text("•")
                                Text("Published \(publishedAt.formatted(date: .abbreviated, time: .omitted))")
                            }
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }

                Section("Actions") {
                    Button(app.status == .live ? "Republish" : "Publish") {
                        Task { await publishApp() }
                    }
                    if let appUrl = app.appUrl, let url = URL(string: appUrl) {
                        Link("Open App", destination: url)
                    }
                }

                Section("Items") {
                    if items.isEmpty {
                        Text("No items yet")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(items) { item in
                            Text(String(describing: item.data))
                                .font(.footnote.monospaced())
                        }
                    }
                }
            }
            .navigationTitle(app.icon ?? "📦")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Done") { dismiss() }
                }
            }
            .task { await refresh() }
            .alert("App Error", isPresented: Binding(
                get: { error != nil },
                set: { if !$0 { error = nil } }
            )) {
                Button("OK") { error = nil }
            } message: {
                Text(error ?? "Something went wrong.")
            }
        }
    }

    private func refresh() async {
        do {
            async let freshApp = appState.getAPIClient().getApp(app.id)
            async let freshItems = appState.getAPIClient().listAppItems(app.id)
            let (resolvedApp, resolvedItems) = try await (freshApp, freshItems)
            app = resolvedApp
            items = resolvedItems
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }

    private func publishApp() async {
        do {
            app = try await appState.getAPIClient().publishApp(
                app.id,
                visibility: app.visibility,
                appUrl: app.appUrl
            )
        } catch {
            self.error = error.userFacingMessage(context: .generic)
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
