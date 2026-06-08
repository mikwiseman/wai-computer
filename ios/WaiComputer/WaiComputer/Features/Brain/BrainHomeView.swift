import SwiftUI
import WaiComputerKit

/// The iOS "Brain" tab — the unified knowledge surface, ported from `MacBrainView`.
///
/// A live source mirror first, then an askable Brain (one cited answer with
/// honest gaps + a freshness read), source-mirror coverage, generated maps,
/// and the browsable living Pages (people/projects/topics → rich dossiers).
/// The captured-items feed and the Review/Compare/Memory surfaces are reachable
/// from the "More" links, keeping the knowledge surface front and center the
/// way the macOS sidebar does.
struct BrainHomeView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: BrainViewModel
    @StateObject private var feed: ContentFeedViewModel
    @State private var showLensForm = false
    @State private var showAdd = false

    let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
        _model = StateObject(wrappedValue: BrainViewModel(apiClient: apiClient))
        _feed = StateObject(wrappedValue: ContentFeedViewModel(apiClient: apiClient))
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        NavigationStack {
            Group {
                if feed.isSearchActive {
                    searchList
                } else {
                    content
                }
            }
            .navigationTitle(t("Brain", "Мозг"))
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $feed.query, prompt: t("Search everything", "Искать везде"))
            .task(id: feed.query) {
                try? await Task.sleep(nanoseconds: 300_000_000)
                if !Task.isCancelled { await feed.search() }
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showAdd = true } label: { Image(systemName: "plus") }
                        .accessibilityIdentifier("brain-add-button")
                }
            }
            .sheet(isPresented: $showAdd) {
                AddAnythingSheet(isPresented: $showAdd, isAdding: feed.isAdding) { text in
                    Task { if await feed.add(text) != nil { showAdd = false; await model.load() } }
                }
            }
            .task {
                await model.load()
                await model.refreshSelectedMapOnceIfNeeded()
                await feed.load()
            }
            .refreshable {
                await model.load()
                await feed.load()
            }
        }
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if model.loading {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(.top, Spacing.huge)
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
            .padding(.top, Spacing.huge)
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.xl) {
                    liveMapSection
                    if model.hasAnything {
                        pagesSection
                    }
                    moreLinks
                }
                .padding(Spacing.lg)
            }
        }
    }

    // MARK: - Live mirror + maps

    private var liveMapSection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(model.activeProjection?.title ?? t("Live Mirror", "Живое зеркало"))
                    .font(Typography.headingLarge)
                Text(model.activeProjection?.summary ?? t(
                    "Add recordings, materials, or Wai chats to build your Brain.",
                    "Добавьте записи, материалы или чаты Wai, чтобы собрать Мозг."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: Spacing.xs) {
                Button {
                    withAnimation { showLensForm.toggle() }
                } label: {
                    Label(t("Create Lens", "Создать линзу"), systemImage: "plus.viewfinder")
                        .font(Typography.labelSmall)
                }
                .buttonStyle(.bordered)
                Spacer()
            }

            if showLensForm {
                HStack(spacing: Spacing.sm) {
                    TextField(
                        t("Map a project, decision, relationship, timeline…",
                          "Карта проекта, решения, связей, хронологии…"),
                        text: $model.lensPrompt
                    )
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await model.createLens() } }
                    Button {
                        Task { await model.createLens() }
                    } label: {
                        Text(model.creatingLens ? t("Generating", "Создаю") : t("Generate", "Создать"))
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.creatingLens || model.lensPrompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }

            if let projection = model.activeProjection {
                askSection(projection)
            }
            brainCoverageSection
            mapStrip
            if let projection = model.activeProjection {
                mapStats(projection)
                focusTemplates()
            }
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private var mapStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Spacing.xs) {
                mapSelectorButton(
                    id: "mirror",
                    title: t("Live Mirror", "Живое зеркало"),
                    detail: t("always current", "всегда актуально")
                )
                ForEach(model.maps) { map in
                    NavigationLink {
                        BrainMapDetailView(map: map, apiClient: apiClient)
                    } label: {
                        mapCard(
                            title: map.title,
                            detail: "\(mapOriginLabel(map.origin)) · \(mapSourceCountText(map.currentRevision))",
                            subdetail: "\(diffSummary(map.currentRevision?.diff)) · \(mapCheckedText(map.currentRevision))",
                            active: false
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.vertical, Spacing.xxs)
        }
    }

    private func mapSelectorButton(id: String, title: String, detail: String) -> some View {
        Button { model.selectedMapId = id } label: {
            mapCard(title: title, detail: detail, subdetail: t("updates from sources", "обновляется из источников"), active: model.selectedMapId == id)
        }
        .buttonStyle(.plain)
    }

    private func mapCard(title: String, detail: String, subdetail: String?, active: Bool) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(Typography.labelSmall.weight(.semibold)).lineLimit(1)
            Text(detail).font(Typography.labelSmall)
                .foregroundStyle(active ? Palette.textSecondary : Palette.textTertiary).lineLimit(1)
            if let subdetail {
                Text(subdetail).font(Typography.labelSmall).foregroundStyle(Palette.textTertiary).lineLimit(1)
            }
        }
        .frame(width: 188, alignment: .leading)
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, Spacing.xs)
        .background(active ? Palette.accentSubtle : Color.primary.opacity(0.045))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func mapStats(_ projection: BrainMapProjection) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Spacing.sm) {
                metricPill("\(projection.nodes.count)", t("cards", "карточек"))
                metricPill("\(projection.edges.count)", t("links", "связей"))
                metricPill("\(projection.citations.count)", t("sources", "источн."))
                if projection.freshness.stale, let weeks = projection.freshness.weeksSince {
                    metricPill("\(weeks)", t("weeks since newest source", "нед. с нового источника"))
                }
            }
        }
    }

    @ViewBuilder
    private func focusTemplates() -> some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: Spacing.sm), GridItem(.flexible(), spacing: Spacing.sm)], spacing: Spacing.sm) {
            diagramTemplate(title: t("Project state", "Состояние проекта"), subtitle: t("status, owners, next steps", "статус, ответственные, шаги"), icon: "list.bullet.rectangle", prompt: t("Map the current state of my active project", "Карта текущего состояния моего активного проекта"))
            diagramTemplate(title: t("Decision", "Решение"), subtitle: t("options & tradeoffs", "варианты и компромиссы"), icon: "arrow.triangle.branch", prompt: t("Map the key decision and its tradeoffs", "Карта ключевого решения и компромиссов"))
            diagramTemplate(title: t("Relationships", "Связи"), subtitle: t("people & projects", "люди и проекты"), icon: "person.2", prompt: t("Map the relationships between people and projects", "Карта связей между людьми и проектами"))
            diagramTemplate(title: t("Timeline", "Хронология"), subtitle: t("how it unfolded", "как развивалось"), icon: "calendar", prompt: t("Map the timeline of what happened", "Карта хронологии событий"))
        }
    }

    private func diagramTemplate(title: String, subtitle: String, icon: String, prompt: String) -> some View {
        Button {
            model.lensPrompt = prompt
            withAnimation { showLensForm = true }
        } label: {
            HStack(alignment: .top, spacing: Spacing.sm) {
                Image(systemName: icon).foregroundStyle(Palette.accent).frame(width: 22)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(Typography.bodySmall.weight(.semibold)).foregroundStyle(Palette.textPrimary)
                    Text(subtitle).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary).lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(Spacing.sm)
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
            .background(Palette.surfaceSubtle)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Palette.border, lineWidth: 1))
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }

    // MARK: - Ask Brain

    private func askSection(_ projection: BrainMapProjection) -> some View {
        let suggestions = askSuggestions(for: projection)
        return VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                Text(t("Ask Brain", "Спросить мозг")).font(Typography.headingMedium)
                Spacer()
                if let answer = model.brainAnswer {
                    Text(answerFreshnessText(answer))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                }
            }

            TextField(
                t("What changed? What is blocked? Who owns the next step?",
                  "Что изменилось? Что блокирует? Кто отвечает за следующий шаг?"),
                text: $model.brainQuestion,
                axis: .vertical
            )
            .textFieldStyle(.roundedBorder)
            .lineLimit(1...3)
            .submitLabel(.search)
            .onSubmit { Task { await model.askBrain() } }
            .accessibilityIdentifier("brain-ask-field")

            HStack(spacing: Spacing.sm) {
                Button {
                    Task { await model.askBrain() }
                } label: {
                    Text(model.askingBrain ? t("Asking", "Спрашиваю") : t("Ask", "Спросить"))
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.brainQuestion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.askingBrain)
                .accessibilityIdentifier("brain-ask-button")

                Button {
                    Task { await model.createLens(promptOverride: model.brainQuestion) }
                } label: {
                    Text(model.creatingLens ? t("Mapping", "Строю") : t("Map it", "Карта"))
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(model.brainQuestion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.creatingLens)
            }

            if !suggestions.isEmpty {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(suggestions.prefix(3), id: \.self) { question in
                        Button {
                            Task { await model.askBrain(questionOverride: question) }
                        } label: {
                            Text(question)
                                .font(Typography.labelSmall)
                                .foregroundStyle(Palette.textSecondary)
                                .multilineTextAlignment(.leading)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, Spacing.sm)
                                .padding(.vertical, Spacing.xs)
                                .background(Color.primary.opacity(0.045))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                        }
                        .buttonStyle(.plain)
                        .disabled(model.askingBrain)
                    }
                }
            }

            if let error = model.brainAskError {
                Text(error).font(Typography.labelSmall).foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let answer = model.brainAnswer {
                answerView(answer)
            }
        }
        .padding(Spacing.md)
        .background(Color.primary.opacity(0.035))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Palette.border, lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func answerView(_ answer: BrainAnswer) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            if !answer.answer.isEmpty {
                Text(answer.answer).font(Typography.bodySmall).foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            if !answer.citations.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: Spacing.xs) {
                        ForEach(answer.citations) { citation in
                            sourceLink(kind: citation.sourceKind, id: citation.sourceId) {
                                Label(brainCitationLabel(citation), systemImage: sourceKindSystemImage(citation.sourceKind))
                                    .font(Typography.labelSmall)
                                    .padding(.horizontal, Spacing.sm)
                                    .padding(.vertical, Spacing.xxs)
                                    .background(Color.primary.opacity(0.06))
                                    .clipShape(Capsule())
                            }
                        }
                    }
                }
            }
            if !answer.gaps.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    Text(t("Gaps", "Пробелы")).font(Typography.labelSmall.weight(.semibold))
                        .foregroundStyle(Palette.textSecondary)
                    ForEach(answer.gaps, id: \.self) { gap in
                        Text("• " + gap).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.top, 2)
            }
        }
        .padding(Spacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    // MARK: - Source coverage

    @ViewBuilder
    private var brainCoverageSection: some View {
        if let overview = model.brainOverview {
            let unlinkedSources = brainUnlinkedRecentSources(overview)
            let linkedSources = brainLinkedRecentSources(overview)
            VStack(alignment: .leading, spacing: Spacing.sm) {
                HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(t("Source mirror", "Зеркало источников"))
                            .font(Typography.label).foregroundStyle(Palette.textSecondary)
                        Text(brainCoverageSummary(overview))
                            .font(Typography.bodySmall.weight(.medium))
                            .foregroundStyle(Palette.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer()
                }

                if overview.pendingReviewCount > 0 || brainUnlinkedSourceCount(overview) > 0 {
                    HStack(spacing: Spacing.sm) {
                        if overview.pendingReviewCount > 0 {
                            metricPill("\(overview.pendingReviewCount)", t("needs review", "на проверке"))
                        }
                        if brainUnlinkedSourceCount(overview) > 0 {
                            Button {
                                Task { await model.repairBrainLinks() }
                            } label: {
                                Text(model.linkingBrainSources ? t("Linking", "Связываю") : t("Link now", "Связать сейчас"))
                            }
                            .buttonStyle(.bordered)
                            .disabled(model.linkingBrainSources)
                        }
                        Spacer()
                    }
                }

                HStack(spacing: Spacing.sm) {
                    sourceCoverageMeter(title: t("Voice", "Голос"), coverage: overview.recordings, systemImage: "waveform")
                    sourceCoverageMeter(title: t("Materials", "Материалы"), coverage: overview.materials, systemImage: "doc.text")
                    sourceCoverageMeter(title: t("Chats", "Чаты"), coverage: overview.chats, systemImage: "bubble.left.and.bubble.right")
                }

                if !unlinkedSources.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Catching up", "В процессе"))
                            .font(Typography.labelSmall.weight(.semibold))
                            .foregroundStyle(Palette.textPrimary)
                        ForEach(unlinkedSources) { source in
                            sourceLink(kind: source.sourceKind, id: source.sourceId) {
                                unlinkedBrainSourceRow(source)
                            }
                        }
                    }
                    .padding(Spacing.sm)
                    .background(Palette.accent.opacity(0.07))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }

                if !linkedSources.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Recent sources", "Свежие источники"))
                            .font(Typography.labelSmall.weight(.semibold))
                            .foregroundStyle(Palette.textSecondary)
                        ForEach(linkedSources) { source in
                            sourceLink(kind: source.sourceKind, id: source.sourceId) {
                                brainOverviewSourceRow(source)
                            }
                        }
                    }
                }

                if !overview.topEntities.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Strong anchors", "Сильные узлы"))
                            .font(Typography.labelSmall.weight(.semibold))
                            .foregroundStyle(Palette.textSecondary)
                        ForEach(overview.topEntities.prefix(5)) { entity in
                            NavigationLink {
                                EntityPageView(entityId: entity.id, name: entity.name, apiClient: apiClient)
                            } label: {
                                brainOverviewEntityRow(entity)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .padding(Spacing.sm)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Palette.border, lineWidth: 1))
        }
    }

    private func sourceCoverageMeter(title: String, coverage: BrainSourceCoverage, systemImage: String) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: systemImage).font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Palette.accent).frame(width: 16)
                Text(title).font(Typography.labelSmall.weight(.semibold)).foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: 0)
                Text("\(coverage.organized)/\(coverage.total)")
                    .font(Typography.labelSmall.weight(.semibold)).foregroundStyle(Palette.textSecondary)
            }
            GeometryReader { geometry in
                let total = max(coverage.total, 1)
                let organizedWidth = geometry.size.width * CGFloat(coverage.organized) / CGFloat(total)
                let summarizedWidth = geometry.size.width * CGFloat(coverage.summarized) / CGFloat(total)
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.06))
                    Capsule().fill(Palette.accent.opacity(0.20)).frame(width: summarizedWidth)
                    Capsule().fill(Palette.accent.opacity(0.75)).frame(width: organizedWidth)
                }
            }
            .frame(height: 6)
        }
        .padding(Spacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func brainOverviewSourceRow(_ source: BrainOverviewSource) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: sourceKindSystemImage(source.sourceKind)).font(.system(size: 11))
                .foregroundStyle(source.entityCount > 0 ? Palette.accent : Palette.textTertiary).frame(width: 16)
            VStack(alignment: .leading, spacing: 1) {
                Text(source.title).font(Typography.bodySmall.weight(.medium))
                    .foregroundStyle(Palette.textPrimary).lineLimit(1)
                Text(brainOverviewSourceDetail(source)).font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary).lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(Spacing.xs)
        .background(Color.primary.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func unlinkedBrainSourceRow(_ source: BrainOverviewSource) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: sourceKindSystemImage(source.sourceKind)).font(.system(size: 11))
                .foregroundStyle(Palette.textTertiary).frame(width: 16)
            VStack(alignment: .leading, spacing: 1) {
                Text(source.title).font(Typography.bodySmall.weight(.medium))
                    .foregroundStyle(Palette.textPrimary).lineLimit(1)
                Text(t("Captured · not in Brain yet", "Сохранено · ещё не в Мозге")).font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary).lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(Spacing.xs)
        .background(Color.primary.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func brainOverviewEntityRow(_ entity: BrainOverviewEntity) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: entityIcon(entity.type)).font(.system(size: 11))
                .foregroundStyle(Palette.accent).frame(width: 16)
            VStack(alignment: .leading, spacing: 1) {
                Text(entity.name).font(Typography.bodySmall.weight(.medium))
                    .foregroundStyle(Palette.textPrimary).lineLimit(1)
                Text(t("\(entity.sourceCount) sources", "\(entity.sourceCount) источн."))
                    .font(Typography.labelSmall).foregroundStyle(Palette.textSecondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.system(size: 10)).foregroundStyle(Palette.textTertiary)
        }
        .padding(Spacing.xs)
        .background(Color.primary.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    // MARK: - Pages

    private var pagesSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(t("Pages", "Страницы")).font(Typography.headingMedium)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Spacing.xs) {
                    ForEach(BrainPageFilter.allCases, id: \.self) { filter in
                        filterChip(filter)
                    }
                }
            }
            TextField(t("Search people, projects, topics…", "Поиск людей, проектов, тем…"), text: $model.searchText)
                .textFieldStyle(.roundedBorder)

            if model.visiblePages.isEmpty {
                wikiEmpty(model.entities.isEmpty
                    ? t("Pages appear as Wai finds people, projects, and topics in your sources.",
                        "Страницы появляются, когда Wai находит людей, проекты и темы в источниках.")
                    : t("No pages match.", "Нет совпадений."))
            } else {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(model.visiblePages) { entity in
                        NavigationLink {
                            EntityPageView(entityId: entity.id, name: entity.name, apiClient: apiClient)
                        } label: {
                            pageRow(entity)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private func filterChip(_ filter: BrainPageFilter) -> some View {
        let active = model.pageFilter == filter
        return Button { model.pageFilter = filter } label: {
            Text(filterLabel(filter))
                .font(Typography.labelSmall)
                .foregroundStyle(active ? Color.white : Palette.textSecondary)
                .padding(.horizontal, Spacing.sm)
                .padding(.vertical, Spacing.xxs)
                .background(active ? Palette.accent : Color.primary.opacity(0.06))
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }

    private func pageRow(_ entity: Entity) -> some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: entityIcon(entity.type.rawValue)).font(.system(size: 12))
                .foregroundStyle(Palette.accent).frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(entity.name).font(Typography.bodySmall.weight(.medium)).foregroundStyle(Palette.textPrimary)
                Text(filterLabel(BrainPageFilter(rawValue: entity.type.rawValue) ?? .topic))
                    .font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
            }
            Spacer()
            let count = entity.sourceCount ?? 0
            Text("\(count) " + (count == 1 ? t("source", "источн.") : t("sources", "источн.")))
                .font(Typography.labelSmall).foregroundStyle(Palette.textTertiary)
            Image(systemName: "chevron.right").font(.system(size: 10)).foregroundStyle(Palette.textTertiary)
        }
        .padding(Spacing.sm)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    // MARK: - More links

    private var moreLinks: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(t("More", "Ещё")).waiSectionHeader()
            linkRow(icon: "tray.full", title: t("Captured", "Сохранённое"), badge: nil) {
                CapturedFeedView(model: feed)
            }
            linkRow(icon: "brain", title: t("Memory", "Память"), badge: nil) {
                MemoryView(apiClient: apiClient)
            }
            linkRow(icon: "checklist", title: t("Review", "На проверку"), badge: feed.pendingReviewCount) {
                ReviewView(apiClient: apiClient)
            }
            linkRow(icon: "tablecells", title: t("Compare", "Сравнить"), badge: nil) {
                ComparisonListView(apiClient: apiClient)
            }
            linkRow(icon: "point.3.connected.trianglepath.dotted", title: t("Graph", "Граф"), badge: nil) {
                BrainGraphView(apiClient: apiClient)
            }
        }
    }

    private func linkRow<Destination: View>(icon: String, title: String, badge: Int?, @ViewBuilder destination: () -> Destination) -> some View {
        NavigationLink {
            destination()
        } label: {
            HStack(spacing: Spacing.sm) {
                Image(systemName: icon).font(.system(size: 15)).foregroundStyle(Palette.accent).frame(width: 24)
                Text(title).font(Typography.body).foregroundStyle(Palette.textPrimary)
                Spacer()
                if let badge, badge > 0 {
                    Text("\(badge)").font(Typography.labelSmall.weight(.semibold)).foregroundStyle(.white)
                        .padding(.horizontal, 7).padding(.vertical, 2).background(Palette.accent, in: Capsule())
                }
                Image(systemName: "chevron.right").font(.system(size: 11)).foregroundStyle(Palette.textTertiary)
            }
            .padding(.vertical, Spacing.sm)
            .padding(.horizontal, Spacing.md)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 10))
        }
        .buttonStyle(.plain)
    }

    // MARK: - Unified search results

    @ViewBuilder
    private var searchList: some View {
        List {
            if feed.isSearching && feed.searchResults.isEmpty {
                ProgressView()
            } else if feed.searchResults.isEmpty {
                Text(t("No results", "Ничего не найдено"))
                    .font(Typography.bodySmall).foregroundStyle(Palette.textSecondary)
            } else {
                Section(header: Text(t("Results", "Результаты"))) {
                    ForEach(feed.searchResults, id: \.chunkId) { hit in
                        NavigationLink {
                            searchDestination(for: hit)
                        } label: {
                            searchHitRow(hit)
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    @ViewBuilder
    private func searchDestination(for hit: UnifiedHit) -> some View {
        if hit.sourceKind == "item" {
            ItemDetailView(itemId: hit.parentId, apiClient: apiClient) {
                Task { await feed.load() }
            }
        } else {
            RecordingDetailView(recording: Recording(id: hit.parentId, type: .meeting, createdAt: Date()))
        }
    }

    private func searchHitRow(_ hit: UnifiedHit) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(hit.title ?? t("Untitled", "Без названия"))
                .font(Typography.body.weight(.medium)).lineLimit(1)
            Text(hit.snippet).font(Typography.bodySmall).foregroundStyle(Palette.textSecondary).lineLimit(2)
            Text(hit.sourceKind == "item" ? hit.kind.uppercased() : t("RECORDING", "ЗАПИСЬ"))
                .font(Typography.labelSmall).foregroundStyle(Palette.textTertiary)
        }
        .padding(.vertical, Spacing.xxs)
    }

    // MARK: - Source navigation helper

    /// Wraps `content` in a NavigationLink to the right detail view for a
    /// recording/material source, or renders it plainly for chats (which live
    /// in the Wai tab and have no standalone iOS detail). Mirrors the macOS
    /// `openSource` intent.
    @ViewBuilder
    private func sourceLink<Content: View>(kind: String, id: String, @ViewBuilder content: () -> Content) -> some View {
        switch kind {
        case "recording":
            NavigationLink {
                RecordingDetailView(recording: Recording(id: id, type: .meeting, createdAt: Date()))
            } label: { content() }
            .buttonStyle(.plain)
        case "item":
            NavigationLink {
                ItemDetailView(itemId: id, apiClient: apiClient) {}
            } label: { content() }
            .buttonStyle(.plain)
        default:
            content()
        }
    }

    // MARK: - Localized helpers (ported from MacBrainView)

    private func wikiEmpty(_ text: String) -> some View {
        Text(text).font(Typography.bodySmall).foregroundStyle(Palette.textSecondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, Spacing.sm)
    }

    private func metricPill(_ value: String, _ label: String) -> some View {
        HStack(spacing: 5) {
            Text(value).font(Typography.labelSmall.weight(.semibold))
            Text(label).font(Typography.labelSmall)
        }
        .foregroundStyle(Palette.textSecondary)
        .padding(.horizontal, Spacing.sm).padding(.vertical, 5)
        .background(Color.primary.opacity(0.045))
        .clipShape(RoundedRectangle(cornerRadius: 7))
    }

    private func askSuggestions(for projection: BrainMapProjection) -> [String] {
        let fromBriefing = projection.briefing?.suggestedQuestions ?? []
        if !fromBriefing.isEmpty { return fromBriefing }
        return [
            t("What changed this week?", "Что изменилось на этой неделе?"),
            t("What is blocked right now?", "Что сейчас заблокировано?"),
            t("Who owns the next step?", "Кто отвечает за следующий шаг?")
        ]
    }

    private func answerFreshnessText(_ answer: BrainAnswer) -> String {
        if answer.freshness.stale, let weeks = answer.freshness.weeksSince {
            return t("Newest evidence is \(weeks) week(s) old.", "Самому новому источнику \(weeks) нед.")
        }
        if answer.freshness.newestSourceAt == nil {
            return t("No dated source.", "Нет источника с датой.")
        }
        return t("Evidence is current.", "Источники актуальны.")
    }

    private func brainCitationLabel(_ citation: BrainAnswerCitation) -> String {
        let title = citation.title?.trimmingCharacters(in: .whitespacesAndNewlines)
        let base = (title?.isEmpty == false ? title : nil) ?? sourceKindLabel(citation.sourceKind)
        guard let startMs = citation.startMs, citation.sourceKind == "recording" else { return base }
        let seconds = max(0, startMs / 1000)
        return "\(base) · \(seconds / 60):\(String(format: "%02d", seconds % 60))"
    }

    private func brainCoverageSummary(_ overview: BrainOverview) -> String {
        let total = overview.recordings.total + overview.materials.total + overview.chats.total
        let organized = overview.recordings.organized + overview.materials.organized + overview.chats.organized
        let unorganized = overview.recordings.unorganized + overview.materials.unorganized + overview.chats.unorganized
        if total == 0 {
            return t("Brain is waiting for recordings, materials, or Wai chats.",
                     "Мозг ждёт записи, материалы или чаты Wai.")
        }
        if unorganized > 0 {
            return t("Wai links everything automatically — \(organized) of \(total) done, \(unorganized) catching up.",
                     "Wai связывает всё автоматически — готово \(organized) из \(total), ещё \(unorganized) в процессе.")
        }
        return t("Wai links everything automatically — all \(total) sources are in your Brain.",
                 "Wai связывает всё автоматически — в Мозге все источники: \(total).")
    }

    private func brainUnlinkedSourceCount(_ overview: BrainOverview) -> Int {
        overview.recordings.unorganized + overview.materials.unorganized + overview.chats.unorganized
    }

    private func brainUnlinkedRecentSources(_ overview: BrainOverview) -> [BrainOverviewSource] {
        Array(overview.recentSources.filter { $0.entityCount == 0 }.prefix(4))
    }

    private func brainLinkedRecentSources(_ overview: BrainOverview) -> [BrainOverviewSource] {
        Array(overview.recentSources.filter { $0.entityCount > 0 }.prefix(5))
    }

    private func brainOverviewSourceDetail(_ source: BrainOverviewSource) -> String {
        if source.entityCount == 0 {
            return sourceKindLabel(source.sourceKind) + " · " + t("not linked yet", "пока без связей")
        }
        return sourceKindLabel(source.sourceKind) + " · \(source.entityCount) " + t("linked node(s)", "связанных узл.")
    }

    private func diffSummary(_ diff: BrainMapDiff?) -> String {
        guard let diff, diff.changed else { return t("Current", "Актуально") }
        var parts: [String] = []
        if diff.sourcesAdded > 0 { parts.append("+\(diff.sourcesAdded) " + t("sources", "источн.")) }
        if diff.nodesAdded > 0 { parts.append("+\(diff.nodesAdded) " + t("cards", "карточек")) }
        if diff.edgesAdded > 0 { parts.append("+\(diff.edgesAdded) " + t("links", "связей")) }
        return parts.isEmpty ? t("Updated", "Обновлено") : parts.joined(separator: " · ")
    }

    private func mapOriginLabel(_ origin: String) -> String {
        switch origin {
        case "inbox": return t("Inbox source", "Источник из инбокса")
        case "agent": return t("Agent", "Агент")
        case "wai": return "Wai"
        default: return t("Brain lens", "Линза мозга")
        }
    }

    private func mapSourceCountText(_ revision: BrainMapRevision?) -> String {
        guard let revision else { return t("not checked", "не проверено") }
        if revision.sourceCount == 0 { return t("no sources", "нет источников") }
        if revision.sourceCount == 1 { return t("1 source", "1 источн.") }
        return t("\(revision.sourceCount) sources", "\(revision.sourceCount) источн.")
    }

    private func mapCheckedText(_ revision: BrainMapRevision?) -> String {
        guard let revision else { return t("not checked yet", "ещё не проверено") }
        let date = String(revision.compiledAt.prefix(10))
        return t("checked \(date)", "проверено \(date)")
    }

    private func sourceKindLabel(_ kind: String) -> String {
        switch kind {
        case "recording": return t("recording", "запись")
        case "item": return t("material", "материал")
        case "chat": return t("Wai chat", "чат Wai")
        default: return kind
        }
    }

    private func sourceKindSystemImage(_ kind: String) -> String {
        switch kind {
        case "recording": return "waveform"
        case "chat": return "bubble.left.and.bubble.right"
        default: return "doc.text"
        }
    }

    private func entityIcon(_ type: String) -> String {
        switch type {
        case "person": return "person"
        case "project": return "folder"
        case "organization": return "building.2"
        default: return "tag"
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
}
