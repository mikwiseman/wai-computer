import SwiftUI
import WaiComputerKit

/// The iOS knowledge-graph browser — a touch-idiomatic adaptation of the macOS
/// Obsidian-style `MacBrainGraphView`. A force-directed canvas is cramped on a
/// phone, so iOS surfaces the same `getBrainGraph` data as a degree-ranked,
/// searchable, kind-filtered list where each node opens its dossier/source.
struct BrainGraphView: View {
    let apiClient: APIClient

    @EnvironmentObject private var languageManager: LanguageManager
    @State private var graph: BrainGraph?
    @State private var loading = true
    @State private var error: String?
    @State private var query = ""
    @State private var kindFilter: GraphKindFilter = .all

    enum GraphKindFilter: String, CaseIterable, Identifiable {
        case all, person, project, topic, source
        var id: String { rawValue }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        Group {
            if let graph {
                content(graph)
            } else if loading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: Spacing.md) {
                    ContentUnavailableViewCompat(
                        t("Couldn't load the graph", "Не удалось загрузить граф"),
                        systemImage: "exclamationmark.triangle",
                        description: error.map { Text($0) }
                    )
                    Button(t("Retry", "Повторить")) { Task { await load() } }
                        .buttonStyle(.borderedProminent)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle(t("Graph", "Граф"))
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: t("Search nodes", "Поиск узлов"))
        .task { await load() }
    }

    private func load() async {
        loading = true
        error = nil
        defer { loading = false }
        do {
            graph = try await apiClient.getBrainGraph(limit: 300)
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func content(_ graph: BrainGraph) -> some View {
        let nodes = visibleNodes(graph)
        let degrees = Dictionary(uniqueKeysWithValues: graph.nodes.map { ($0.id, $0.degree) })
        return List {
            Section {
                HStack(spacing: Spacing.sm) {
                    statTile("\(graph.nodes.count)", t("nodes", "узлов"))
                    statTile("\(graph.edges.count)", t("links", "связей"))
                }
                .listRowInsets(EdgeInsets(top: Spacing.sm, leading: 0, bottom: Spacing.sm, trailing: 0))
                .listRowBackground(Color.clear)

                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: Spacing.xs) {
                        ForEach(GraphKindFilter.allCases) { filter in
                            filterChip(filter)
                        }
                    }
                }
                .listRowBackground(Color.clear)
            }

            if nodes.isEmpty {
                Text(t("No nodes match.", "Нет совпадений."))
                    .font(Typography.bodySmall).foregroundStyle(Palette.textSecondary)
            } else {
                Section(header: Text(t("Most connected", "Самые связанные"))) {
                    ForEach(nodes) { node in
                        nodeRow(node, degree: degrees[node.id] ?? node.degree)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    private func visibleNodes(_ graph: BrainGraph) -> [BrainGraphNode] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return graph.nodes
            .filter { node in
                let matchesKind: Bool
                switch kindFilter {
                case .all: matchesKind = true
                case .source: matchesKind = (node.kind == "item" || node.kind == "recording")
                default: matchesKind = node.kind == kindFilter.rawValue
                }
                return matchesKind && (q.isEmpty || node.label.lowercased().contains(q))
            }
            .sorted { $0.degree > $1.degree }
    }

    @ViewBuilder
    private func nodeRow(_ node: BrainGraphNode, degree: Int) -> some View {
        switch node.kind {
        case "person", "project", "topic", "organization":
            NavigationLink {
                EntityPageView(entityId: node.id, name: node.label, apiClient: apiClient)
            } label: { rowLabel(node, degree: degree) }
        case "recording":
            NavigationLink {
                RecordingDetailView(recording: Recording(id: sourceId(node.id), type: .meeting, createdAt: Date()))
            } label: { rowLabel(node, degree: degree) }
        case "item":
            NavigationLink {
                ItemDetailView(itemId: sourceId(node.id), apiClient: apiClient) {}
            } label: { rowLabel(node, degree: degree) }
        default:
            rowLabel(node, degree: degree)
        }
    }

    /// Graph source nodes are id-prefixed (e.g. `recording:<id>`); strip the
    /// prefix when routing to a detail view.
    private func sourceId(_ id: String) -> String {
        guard let range = id.range(of: ":") else { return id }
        return String(id[range.upperBound...])
    }

    private func rowLabel(_ node: BrainGraphNode, degree: Int) -> some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: nodeIcon(node.kind)).font(.system(size: 12))
                .foregroundStyle(nodeColor(node.kind)).frame(width: 20)
            VStack(alignment: .leading, spacing: 1) {
                Text(node.label).font(Typography.body.weight(.medium)).lineLimit(1)
                Text(kindLabel(node.kind)).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
            }
            Spacer()
            Text(t("\(degree) links", "\(degree) связей")).font(Typography.labelSmall).foregroundStyle(Palette.textTertiary)
        }
        .padding(.vertical, Spacing.xxs)
    }

    private func filterChip(_ filter: GraphKindFilter) -> some View {
        let active = kindFilter == filter
        return Button { kindFilter = filter } label: {
            Text(filterLabel(filter))
                .font(Typography.labelSmall)
                .foregroundStyle(active ? Color.white : Palette.textSecondary)
                .padding(.horizontal, Spacing.sm).padding(.vertical, Spacing.xxs)
                .background(active ? Palette.accent : Color.primary.opacity(0.06))
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }

    private func statTile(_ value: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value).font(Typography.displaySmall).foregroundStyle(Palette.textPrimary)
            Text(label).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func nodeIcon(_ kind: String) -> String {
        switch kind {
        case "person": return "person"
        case "project": return "folder"
        case "organization": return "building.2"
        case "topic": return "tag"
        case "recording": return "waveform"
        case "item": return "doc.text"
        default: return "circle"
        }
    }

    private func nodeColor(_ kind: String) -> Color {
        switch kind {
        case "recording", "item": return .blue
        default: return Palette.accent
        }
    }

    private func kindLabel(_ kind: String) -> String {
        switch kind {
        case "person": return t("Person", "Человек")
        case "project": return t("Project", "Проект")
        case "organization": return t("Organization", "Организация")
        case "topic": return t("Topic", "Тема")
        case "recording": return t("Recording", "Запись")
        case "item": return t("Material", "Материал")
        default: return kind
        }
    }

    private func filterLabel(_ filter: GraphKindFilter) -> String {
        switch filter {
        case .all: return t("All", "Все")
        case .person: return t("People", "Люди")
        case .project: return t("Projects", "Проекты")
        case .topic: return t("Topics", "Темы")
        case .source: return t("Sources", "Источники")
        }
    }
}
