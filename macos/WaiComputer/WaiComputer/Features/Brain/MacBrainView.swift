import SwiftUI
import WaiComputerKit

enum BrainPageFilter: String, CaseIterable {
    case all
    case person
    case project
    case topic
}

/// The macOS "Brain" view: a browsable WIKI of compiled pages (people /
/// projects / topics). Each page is a cited, self-maintaining dossier
/// (overview · facts · timeline · related · questions · actions · citations).
/// "Ask Wai about X" deep-links into the Inbox chat scoped to that entity.
/// Ask + workflows live in Wai/Inbox; Brain is read-only knowledge.
struct MacBrainView: View {
    let apiClient: APIClient
    let onOpenSource: (InboxDetailRef) -> Void
    let onOpenInbox: (() -> Void)?
    /// (entityId, name) -> open the Inbox/Wai chat scoped to that page.
    let onAskWaiAboutEntity: ((String, String) -> Void)?

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacBrainViewModel

    init(
        apiClient: APIClient,
        onOpenSource: @escaping (InboxDetailRef) -> Void = { _ in },
        onOpenInbox: (() -> Void)? = nil,
        onAskWaiAboutEntity: ((String, String) -> Void)? = nil
    ) {
        self.apiClient = apiClient
        self.onOpenSource = onOpenSource
        self.onOpenInbox = onOpenInbox
        self.onAskWaiAboutEntity = onAskWaiAboutEntity
        _model = StateObject(wrappedValue: MacBrainViewModel(apiClient: apiClient))
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            content
        }
        .task { await model.load() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(t("Brain", "Мозг")).font(Typography.displaySmall)
            Text(t(
                "Your wiki — the people, projects, and topics Wai compiles from everything you capture.",
                "Ваша вики — люди, проекты и темы, которые Wai собирает из всего, что вы фиксируете."
            ))
            .font(Typography.bodySmall)
            .foregroundStyle(Palette.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.xl)
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
        } else if model.selectedEntity != nil {
            dossierView
        } else {
            unifiedView
        }
    }

    // MARK: - Wiki index

    private var unifiedView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                if model.entities.isEmpty {
                    startWithSources
                } else {
                    pagesSection
                }
            }
            .padding(Spacing.xl)
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
    }

    private var pagesSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                Text(t("Pages", "Страницы")).font(Typography.headingSmall)
                Spacer()
                HStack(spacing: Spacing.xs) {
                    ForEach(BrainPageFilter.allCases, id: \.self) { filter in
                        filterChip(filter)
                    }
                }
            }
            TextField(
                t("Search people, projects, topics…", "Поиск людей, проектов, тем…"),
                text: $model.searchText
            )
            .textFieldStyle(.roundedBorder)

            if model.visiblePages.isEmpty {
                wikiEmpty(model.entities.isEmpty
                    ? t("Pages appear as Wai finds people, projects, and topics in your sources.",
                        "Страницы появляются, когда Wai находит людей, проекты и темы в ваших источниках.")
                    : t("No pages match.", "Нет совпадений."))
            } else {
                LazyVStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(model.visiblePages) { entity in
                        pageRow(entity)
                    }
                }
            }
        }
    }

    private func filterChip(_ filter: BrainPageFilter) -> some View {
        let active = model.pageFilter == filter
        return Button {
            model.pageFilter = filter
        } label: {
            Text(filterLabel(filter))
                .font(Typography.labelSmall)
                .foregroundStyle(active ? Palette.textPrimary : Palette.textSecondary)
                .padding(.horizontal, Spacing.sm)
                .padding(.vertical, Spacing.xxs)
                .background(active ? Palette.surfaceSubtle : Color.clear)
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }

    private func pageRow(_ entity: Entity) -> some View {
        Button {
            model.openEntity(id: entity.id, name: entity.name)
        } label: {
            HStack(spacing: Spacing.sm) {
                Image(systemName: entityIcon(entity.type.rawValue))
                    .font(.system(size: 11))
                    .foregroundStyle(Palette.accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(entity.name).font(Typography.bodySmall.weight(.medium))
                    if let snippet = entity.overviewSnippet, !snippet.isEmpty {
                        Text(snippet)
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.textSecondary)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                    } else {
                        Text(entityTypeLabel(entity.type.rawValue))
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.textSecondary)
                    }
                }
                Spacer()
                let count = entity.sourceCount ?? 0
                Text("\(count) " + (count == 1 ? t("source", "источн.") : t("sources", "источн.")))
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
            .padding(Spacing.sm)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }

    private var startWithSources: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(t("Start with sources", "Начните с источников")).font(Typography.headingSmall)
            wikiEmpty(t(
                "Add recordings, materials, or Wai chats from Inbox to build your Brain.",
                "Добавьте записи, материалы или чаты Wai из инбокса."
            ))
            if let onOpenInbox {
                Button(t("Open Inbox", "Открыть инбокс")) { onOpenInbox() }
                    .buttonStyle(.bordered)
            }
        }
    }

    // MARK: - Dossier (living page)

    @ViewBuilder
    private var dossierView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                Button {
                    model.closeEntity()
                } label: {
                    Label(t("Back to Pages", "Назад к страницам"), systemImage: "chevron.left")
                        .font(Typography.labelSmall)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Palette.accent)

                if let entity = model.selectedEntity {
                    HStack(alignment: .top) {
                        wikiHeader(entity)
                        Spacer()
                        if let onAskWaiAboutEntity {
                            Button {
                                onAskWaiAboutEntity(entity.id, entity.name)
                            } label: {
                                Label(
                                    t("Ask Wai about \(entity.name)", "Спросить Wai про \(entity.name)"),
                                    systemImage: "sparkles"
                                )
                                .font(Typography.labelSmall)
                            }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.small)
                        }
                    }
                    if model.pageLoading {
                        ProgressView()
                    } else if let pageError = model.pageError {
                        Text(pageError).font(Typography.bodySmall).foregroundStyle(.red)
                    } else if let page = model.entityPage {
                        wikiBody(page)
                    }
                }
            }
            .padding(Spacing.xl)
            .frame(maxWidth: 760, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
    }

    private func wikiHeader(_ entity: MacBrainViewModel.SelectedEntity) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            if let page = model.entityPage {
                Text(page.type.uppercased())
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
            Text(entity.name).font(Typography.headingSmall)
            if let page = model.entityPage {
                Text("\(page.mentionCount) " + t("mentions", "упоминаний"))
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    @ViewBuilder
    private func wikiBody(_ page: EntityPage) -> some View {
        wikiSection(t("Overview", "Обзор")) {
            Text(page.overview)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }

        wikiSection(t("Facts", "Факты")) {
            if page.facts.isEmpty {
                wikiEmpty(t("No extracted facts yet.", "Пока нет фактов."))
            } else {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(page.facts) { fact in
                        wikiEvidenceRow(
                            title: fact.text,
                            detail: citationTitle(fact.citationIds, page: page)
                        )
                    }
                }
            }
        }

        wikiSection(t("Timeline", "Хронология")) {
            if page.timeline.isEmpty {
                wikiEmpty(t("No timeline events yet.", "Пока нет событий."))
            } else {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(page.timeline) { event in
                        wikiEvidenceRow(
                            title: event.title,
                            detail: event.description ?? citationTitle(event.citationIds, page: page)
                        )
                    }
                }
            }
        }

        wikiSection(t("Related", "Связанные")) {
            if !page.relatedExplanations.isEmpty {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(page.relatedExplanations) { rel in
                        Button {
                            model.openEntity(id: rel.id, name: rel.name)
                        } label: {
                            VStack(alignment: .leading, spacing: Spacing.xxs) {
                                HStack(spacing: Spacing.xs) {
                                    Image(systemName: entityIcon(rel.type))
                                        .font(.system(size: 10))
                                        .foregroundStyle(Palette.accent)
                                    Text(rel.name).font(Typography.bodySmall.weight(.medium))
                                    Spacer()
                                    Text("\(rel.shared)")
                                        .font(Typography.labelSmall)
                                        .foregroundStyle(Palette.textTertiary)
                                }
                                Text(rel.explanation)
                                    .font(Typography.labelSmall)
                                    .foregroundStyle(Palette.textSecondary)
                            }
                            .padding(Spacing.sm)
                            .background(Palette.surfaceSubtle)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                        }
                        .buttonStyle(.plain)
                    }
                }
            } else {
                wikiEmpty(t("No related entities yet.", "Пока нет связанных сущностей."))
            }
        }

        wikiSection(t("Questions", "Вопросы")) {
            if page.questions.isEmpty {
                wikiEmpty(t("No open questions found.", "Открытых вопросов не найдено."))
            } else {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(page.questions) { question in
                        wikiEvidenceRow(
                            title: question.text,
                            detail: citationTitle(question.citationIds, page: page)
                        )
                    }
                }
            }
        }

        wikiSection(t("Actions", "Действия")) {
            if page.actions.isEmpty {
                wikiEmpty(t("No action items found.", "Действий не найдено."))
            } else {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(page.actions) { action in
                        wikiEvidenceRow(
                            title: action.text,
                            detail: actionDetail(action, page: page)
                        )
                    }
                }
            }
        }

        wikiSection(t("Citations", "Цитаты")) {
            if page.citations.isEmpty {
                wikiEmpty(t("Nothing mentions this yet.", "Пока ничего не упоминает это."))
            } else {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(page.citations) { source in
                        Button {
                            openSource(kind: source.sourceKind, id: source.sourceId)
                        } label: {
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
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private func wikiSection<Content: View>(
        _ title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(title).font(Typography.label)
                .foregroundStyle(Palette.textSecondary)
            content()
        }
    }

    private func wikiEmpty(_ text: String) -> some View {
        Text(text)
            .font(Typography.bodySmall)
            .foregroundStyle(Palette.textTertiary)
    }

    private func wikiEvidenceRow(title: String, detail: String?) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(title)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            if let detail, !detail.isEmpty {
                Text(detail)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func citationTitle(_ ids: [String], page: EntityPage) -> String? {
        let titlesById = Dictionary(
            uniqueKeysWithValues: page.citations.map { ($0.id, $0.title) }
        )
        let titles = ids.compactMap { titlesById[$0] }
        return titles.isEmpty ? nil : titles.prefix(3).joined(separator: ", ")
    }

    private func actionDetail(_ action: EntityPageAction, page: EntityPage) -> String? {
        let detail = [action.owner, action.status, citationTitle(action.citationIds, page: page)]
            .compactMap { $0 }
            .joined(separator: " · ")
        return detail.isEmpty ? nil : detail
    }

    // MARK: - Shared helpers

    private func openSource(kind: String, id: String) {
        guard let sourceKind = InboxSourceKind(rawValue: kind) else { return }
        guard sourceKind == .recording || sourceKind == .item || sourceKind == .chat else { return }
        onOpenSource(InboxDetailRef(kind: sourceKind, id: id))
    }

    private func entityIcon(_ type: String) -> String {
        switch type {
        case "person": return "person"
        case "project": return "folder"
        case "organization": return "building.2"
        default: return "tag"
        }
    }

    private func entityTypeLabel(_ type: String) -> String {
        switch type {
        case "person": return t("Person", "Человек")
        case "project": return t("Project", "Проект")
        case "organization": return t("Organization", "Организация")
        default: return t("Topic", "Тема")
        }
    }

    private func filterLabel(_ filter: BrainPageFilter) -> String {
        switch filter {
        case .all: return t("All", "Все")
        case .person: return t("People", "Люди")
        case .project: return t("Projects", "Проекты")
        case .topic: return t("Topics", "Темы")
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

    @Published var loading = true
    @Published var errorMessage: String?

    @Published var entities: [Entity] = [] { didSet { recomputeVisiblePages() } }
    @Published var pageFilter: BrainPageFilter = .all { didSet { recomputeVisiblePages() } }
    @Published var searchText = "" { didSet { recomputeVisiblePages() } }
    /// Memoized filtered pages. Recomputed only when entities / filter / query
    /// change, instead of re-filtering the whole array on every body render.
    @Published private(set) var visiblePages: [Entity] = []

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
            entities = try await apiClient.listEntities(limit: 200)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func recomputeVisiblePages() {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        visiblePages = entities.filter { entity in
            (pageFilter == .all || entity.type.rawValue == pageFilter.rawValue)
                && (query.isEmpty || entity.name.lowercased().contains(query))
        }
    }

    func openEntity(id: String, name: String) {
        selectedEntity = SelectedEntity(id: id, name: name)
        entityPage = nil
        Task { await loadEntityPage(id) }
    }

    func closeEntity() {
        selectedEntity = nil
        entityPage = nil
        pageError = nil
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
