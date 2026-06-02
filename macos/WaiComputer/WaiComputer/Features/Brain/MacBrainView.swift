import SwiftUI
import WaiComputerKit

enum MacBrainTab: String, CaseIterable {
    case index
    case wiki
    case graph
}

/// The macOS "Brain" view: a knowledge graph of the people / topics / projects
/// across everything captured. Mirrors the web tri-view — Index (scannable
/// categorized list), Wiki (entity pages with backlinks + related), and a
/// force-directed Graph (Obsidian-style). Honest empty / error+retry states.
struct MacBrainView: View {
    let apiClient: APIClient

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacBrainViewModel

    init(apiClient: APIClient) {
        self.apiClient = apiClient
        _model = StateObject(wrappedValue: MacBrainViewModel(apiClient: apiClient))
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            tabBar
            Divider()
            content
        }
        .task { await model.load() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(t("Brain", "Мозг")).font(Typography.displaySmall)
            Text(t("People, topics and projects across everything you've captured.",
                   "Люди, темы и проекты по всему, что вы сохранили."))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.xl)
    }

    private var tabBar: some View {
        HStack(spacing: Spacing.sm) {
            tabButton(.index, t("Index", "Индекс"))
            tabButton(.wiki, t("Wiki", "Вики"))
            tabButton(.graph, t("Graph", "Граф"))
            Spacer()
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.sm)
    }

    private func tabButton(_ tab: MacBrainTab, _ label: String) -> some View {
        Button {
            model.tab = tab
        } label: {
            Text(label)
                .font(Typography.label)
                .foregroundStyle(model.tab == tab ? Palette.textPrimary : Palette.textSecondary)
                .padding(.horizontal, Spacing.sm)
                .padding(.vertical, Spacing.xxs)
        }
        .buttonStyle(.plain)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(model.tab == tab ? Palette.accent : Color.clear)
                .frame(height: 2)
        }
    }

    @ViewBuilder
    private var content: some View {
        if model.loading {
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let message = model.errorMessage {
            VStack(spacing: Spacing.md) {
                ContentUnavailableViewCompat(
                    t("Couldn't load your brain", "Не удалось загрузить мозг"),
                    systemImage: "exclamationmark.triangle",
                    description: Text(message)
                )
                Button(t("Retry", "Повторить")) { Task { await model.load() } }
                    .buttonStyle(.borderedProminent)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            switch model.tab {
            case .index: indexView
            case .wiki: wikiView
            case .graph: graphView
            }
        }
    }

    // MARK: - Graph

    @ViewBuilder
    private var graphView: some View {
        if let graph = model.graph, !graph.nodes.isEmpty {
            MacBrainGraphView(graph: graph) { node in
                // Only entity nodes have wiki pages; source nodes (item/recording)
                // are drawn but not navigable here (there's no page to open).
                if node.kind == "person" || node.kind == "topic" || node.kind == "project" {
                    model.openEntity(id: node.id, name: node.label)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            emptyBrain
        }
    }

    // MARK: - Index

    @ViewBuilder
    private var indexView: some View {
        let groups = model.entityGroups
        if groups.isEmpty {
            emptyBrain
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.xl) {
                    ForEach(groups, id: \.kind) { group in
                        VStack(alignment: .leading, spacing: Spacing.xs) {
                            Text(groupTitle(group.kind)).font(Typography.headingSmall)
                            ForEach(group.nodes) { node in
                                entityRow(node)
                            }
                        }
                    }
                }
                .padding(Spacing.xl)
                .frame(maxWidth: 760, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
        }
    }

    private func entityRow(_ node: BrainGraphNode) -> some View {
        Button {
            model.openEntity(id: node.id, name: node.label)
        } label: {
            HStack(spacing: Spacing.xs) {
                Image(systemName: entityIcon(node.kind))
                    .font(.system(size: 11))
                    .foregroundStyle(Palette.accent)
                Text(node.label).font(Typography.bodySmall.weight(.medium))
                Spacer()
                Text("\(node.degree)")
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
            .padding(Spacing.sm)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }

    // MARK: - Wiki

    @ViewBuilder
    private var wikiView: some View {
        if let entity = model.selectedEntity {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.lg) {
                    wikiHeader(entity)
                    if model.pageLoading {
                        ProgressView()
                    } else if let pageError = model.pageError {
                        Text(pageError).font(Typography.bodySmall).foregroundStyle(.red)
                    } else if let page = model.entityPage {
                        wikiBody(page)
                    }
                }
                .padding(Spacing.xl)
                .frame(maxWidth: 760, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
        } else {
            ContentUnavailableViewCompat(
                t("Pick a person or topic", "Выберите человека или тему"),
                systemImage: "doc.text.magnifyingglass",
                description: Text(t("Choose one from the Index to read its page.",
                                    "Выберите элемент в Индексе, чтобы открыть страницу."))
            )
        }
    }

    private func wikiHeader(_ entity: MacBrainViewModel.SelectedEntity) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(entity.name).font(Typography.headingSmall)
            if let page = model.entityPage {
                Text("\(page.type.uppercased()) · \(page.mentionCount) "
                     + t("mentions", "упоминаний"))
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    @ViewBuilder
    private func wikiBody(_ page: EntityPage) -> some View {
        if !page.related.isEmpty {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Related", "Связанные")).font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)
                ForEach(page.related) { rel in
                    Button {
                        model.openEntity(id: rel.id, name: rel.name)
                    } label: {
                        HStack(spacing: Spacing.xs) {
                            Image(systemName: entityIcon(rel.type))
                                .font(.system(size: 10))
                                .foregroundStyle(Palette.accent)
                            Text(rel.name).font(Typography.bodySmall)
                            Spacer()
                            Text("\(rel.shared)")
                                .font(Typography.labelSmall)
                                .foregroundStyle(Palette.textTertiary)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }

        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(t("Sources", "Источники")).font(Typography.label)
                .foregroundStyle(Palette.textSecondary)
            if page.sources.isEmpty {
                Text(t("Nothing mentions this yet.", "Пока ничего не упоминает это."))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textTertiary)
            } else {
                ForEach(page.sources) { source in
                    VStack(alignment: .leading, spacing: Spacing.xxs) {
                        HStack(spacing: Spacing.xs) {
                            Text(source.sourceKind.uppercased())
                                .font(Typography.labelSmall)
                                .foregroundStyle(Palette.textTertiary)
                            Text(source.title).font(Typography.bodySmall.weight(.medium))
                        }
                        if let context = source.context, !context.isEmpty {
                            Text(context)
                                .font(Typography.labelSmall)
                                .foregroundStyle(Palette.textSecondary)
                        }
                    }
                    .padding(Spacing.sm)
                    .background(Palette.surfaceSubtle)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }
            }
        }
    }

    // MARK: - Shared

    private var emptyBrain: some View {
        ContentUnavailableViewCompat(
            t("Your brain is empty", "Ваш мозг пуст"),
            systemImage: "brain",
            description: Text(t(
                "As you record and add content, the people & topics they mention appear here.",
                "По мере записей и добавления материалов здесь появятся люди и темы."
            ))
        )
    }

    private func entityIcon(_ type: String) -> String {
        switch type {
        case "person": return "person"
        case "project": return "folder"
        case "organization": return "building.2"
        default: return "tag"
        }
    }

    private func groupTitle(_ kind: String) -> String {
        switch kind {
        case "person": return t("People", "Люди")
        case "topic": return t("Topics", "Темы")
        case "project": return t("Projects", "Проекты")
        default: return kind.capitalized
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

@MainActor
final class MacBrainViewModel: ObservableObject {
    struct SelectedEntity: Equatable {
        let id: String
        let name: String
    }

    struct EntityGroup {
        let kind: String
        let nodes: [BrainGraphNode]
    }

    @Published var graph: BrainGraph?
    @Published var loading = true
    @Published var errorMessage: String?
    @Published var tab: MacBrainTab = .index
    @Published var selectedEntity: SelectedEntity?
    @Published var entityPage: EntityPage?
    @Published var pageLoading = false
    @Published var pageError: String?

    private let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        loading = true
        errorMessage = nil
        defer { loading = false }
        do {
            // No-fallback: a transient failure must NOT look like "empty brain".
            graph = try await apiClient.getBrainGraph()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    var entityGroups: [EntityGroup] {
        guard let graph else { return [] }
        var byKind: [String: [BrainGraphNode]] = [:]
        for node in graph.nodes where node.kind != "item" && node.kind != "recording" {
            byKind[node.kind, default: []].append(node)
        }
        return ["person", "topic", "project"].compactMap { kind in
            guard let nodes = byKind[kind], !nodes.isEmpty else { return nil }
            return EntityGroup(kind: kind, nodes: nodes.sorted { $0.degree > $1.degree })
        }
    }

    func openEntity(id: String, name: String) {
        selectedEntity = SelectedEntity(id: id, name: name)
        entityPage = nil
        tab = .wiki
        Task { await loadEntityPage(id) }
    }

    func loadEntityPage(_ id: String) async {
        pageLoading = true
        pageError = nil
        defer { pageLoading = false }
        do {
            entityPage = try await apiClient.getEntityPage(id: id)
        } catch {
            pageError = error.localizedDescription
        }
    }
}
