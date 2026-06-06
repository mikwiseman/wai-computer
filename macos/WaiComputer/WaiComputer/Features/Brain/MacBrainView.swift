import SwiftUI
import WaiComputerKit

enum BrainPageFilter: String, CaseIterable {
    case all
    case person
    case project
    case topic
}

/// The macOS "Brain" view: a live mirror first, generated maps next, then the
/// browsable living Pages and curated knowledge. Ask/workflows stay in Wai and
/// Inbox; Brain is the up-to-date visual surface.
struct MacBrainView: View {
    let apiClient: APIClient
    let initialMapId: String?
    let onOpenSource: (InboxDetailRef) -> Void
    let onOpenInbox: (() -> Void)?
    let onOpenWai: ((BrainSpace) -> Void)?
    let onInitialMapConsumed: () -> Void

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacBrainViewModel
    @State private var shareEmail = ""
    @State private var shareRole = "viewer"
    @State private var showLensForm = false

    init(
        apiClient: APIClient,
        initialMapId: String? = nil,
        onOpenSource: @escaping (InboxDetailRef) -> Void = { _ in },
        onOpenInbox: (() -> Void)? = nil,
        onOpenWai: ((BrainSpace) -> Void)? = nil,
        onInitialMapConsumed: @escaping () -> Void = {}
    ) {
        self.apiClient = apiClient
        self.initialMapId = initialMapId
        self.onOpenSource = onOpenSource
        self.onOpenInbox = onOpenInbox
        self.onOpenWai = onOpenWai
        self.onInitialMapConsumed = onInitialMapConsumed
        _model = StateObject(wrappedValue: MacBrainViewModel(
            apiClient: apiClient,
            initialMapId: initialMapId
        ))
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            content
        }
        .task {
            consumeInitialMapIfNeeded(initialMapId)
            await model.load()
            await model.refreshSelectedMapOnceIfNeeded()
        }
        .onChangeCompat(of: initialMapId) { _, next in
            consumeInitialMapIfNeeded(next)
        }
        .onChangeCompat(of: model.selectedMapId) { _, _ in
            Task { await model.refreshSelectedMapOnceIfNeeded() }
        }
        .onChangeCompat(of: model.selectedSpaceId) { _, _ in
            guard !model.loading else { return }
            Task { await model.loadSelectedSpace() }
        }
    }

    private func consumeInitialMapIfNeeded(_ mapId: String?) {
        guard let mapId, !mapId.isEmpty else { return }
        model.selectInitialMap(mapId)
        onInitialMapConsumed()
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(t("Brain", "Мозг")).font(Typography.displaySmall)
            Text(t("A live mirror of what Wai knows, plus generated maps that stay tied to sources.",
                   "Живое зеркало того, что знает Wai, и карты, которые остаются привязаны к источникам."))
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

    // MARK: - Unified surface

    private var unifiedView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                liveMapSection
                if model.hasAnything {
                    pagesSection
                    curatedDisclosure
                } else {
                    startWithSources
                }
            }
            .padding(Spacing.xl)
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
    }

    // MARK: - Live mirror + maps

    private var liveMapSection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .top, spacing: Spacing.md) {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(model.activeProjection?.title ?? t("Live Mirror", "Живое зеркало"))
                        .font(Typography.headingSmall)
                    Text(model.activeProjection?.summary ?? t(
                        "Add recordings or materials from Inbox to build your Brain.",
                        "Добавьте записи или материалы из инбокса."
                    ))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                HStack(spacing: Spacing.xs) {
                    Button {
                        showLensForm.toggle()
                    } label: {
                        Label(t("Create Lens", "Создать линзу"), systemImage: "plus.viewfinder")
                    }
                    .buttonStyle(.bordered)
                    if model.activeMap != nil {
                        Button {
                            Task { await model.refreshActiveMap() }
                        } label: {
                            Label(
                                model.refreshingMapId == model.activeMap?.id ? t("Refreshing", "Обновляю") : t("Refresh", "Обновить"),
                                systemImage: "arrow.clockwise"
                            )
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.refreshingMapId == model.activeMap?.id)
                    }
                    if model.activeMap?.status == "draft" {
                        Button(t("Keep", "Сохранить")) {
                            Task { await model.keepActiveMap() }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
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
                            .frame(minWidth: 96)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.creatingLens || model.lensPrompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }

            brainCoverageSection
            mapStrip

            if let projection = model.activeProjection {
                brainAskSection(projection)
                if model.selectedMapId == "mirror" {
                    mirrorFocusSurface(projection)
                    mapStats(projection)
                } else {
                    generatedMapSurface(projection)
                }
            } else {
                wikiEmpty(t("No source map yet.", "Карты источников пока нет."))
            }
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder
    private var brainCoverageSection: some View {
        if let overview = model.brainOverview {
            let unlinkedSources = brainUnlinkedRecentSources(overview)
            let linkedSources = brainLinkedRecentSources(overview)
            VStack(alignment: .leading, spacing: Spacing.sm) {
                HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(t("Source mirror", "Зеркало источников"))
                            .font(Typography.label)
                            .foregroundStyle(Palette.textSecondary)
                        Text(brainCoverageSummary(overview))
                            .font(Typography.bodySmall.weight(.medium))
                            .foregroundStyle(Palette.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer()
                    if overview.pendingReviewCount > 0 {
                        metricPill(
                            "\(overview.pendingReviewCount)",
                            t("needs review", "на проверке")
                        )
                    }
                    if let sync = model.brainSyncResult, sync.createdMentions > 0 {
                        metricPill(
                            "\(sync.sourcesWithEntities)",
                            t("synced now", "связано сейчас")
                        )
                    }
                    if brainUnlinkedSourceCount(overview) > 0 {
                        Button {
                            Task { await model.repairBrainLinks() }
                        } label: {
                            Text(model.linkingBrainSources ? t("Linking", "Связываю") : t("Link summaries", "Связать summary"))
                                .frame(minWidth: 96)
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.linkingBrainSources)
                    }
                }

                HStack(spacing: Spacing.sm) {
                    sourceCoverageMeter(
                        title: t("Voice memos", "Голосовые"),
                        coverage: overview.recordings,
                        systemImage: "waveform"
                    )
                    sourceCoverageMeter(
                        title: t("Materials", "Материалы"),
                        coverage: overview.materials,
                        systemImage: "doc.text"
                    )
                }

                if !unlinkedSources.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        HStack(alignment: .firstTextBaseline, spacing: Spacing.xs) {
                            Text(t("Needs linking", "Нужно связать"))
                                .font(Typography.labelSmall.weight(.semibold))
                                .foregroundStyle(Palette.textPrimary)
                            Spacer()
                            Text(t(
                                "\(brainUnlinkedSourceCount(overview)) source(s)",
                                "\(brainUnlinkedSourceCount(overview)) источн."
                            ))
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.textSecondary)
                        }
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: Spacing.xs) {
                            ForEach(unlinkedSources) { source in
                                Button {
                                    openSource(kind: source.sourceKind, id: source.sourceId)
                                } label: {
                                    unlinkedBrainSourceRow(source)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    .padding(Spacing.sm)
                    .background(Palette.accent.opacity(0.07))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }

                HStack(alignment: .top, spacing: Spacing.lg) {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Recent sources", "Свежие источники"))
                            .font(Typography.labelSmall.weight(.semibold))
                            .foregroundStyle(Palette.textSecondary)
                        if linkedSources.isEmpty {
                            wikiEmpty(t("No linked recent sources yet.", "Пока нет свежих источников со связями."))
                        } else {
                            ForEach(linkedSources) { source in
                                Button {
                                    openSource(kind: source.sourceKind, id: source.sourceId)
                                } label: {
                                    brainOverviewSourceRow(source)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .topLeading)

                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Strong anchors", "Сильные узлы"))
                            .font(Typography.labelSmall.weight(.semibold))
                            .foregroundStyle(Palette.textSecondary)
                        if overview.topEntities.isEmpty {
                            wikiEmpty(t("No linked people, projects, or topics yet.",
                                        "Пока нет связанных людей, проектов или тем."))
                        } else {
                            ForEach(overview.topEntities.prefix(5)) { entity in
                                Button {
                                    model.openEntity(id: entity.id, name: entity.name)
                                } label: {
                                    brainOverviewEntityRow(entity)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .topLeading)
                }
            }
            .padding(Spacing.sm)
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color.primary.opacity(0.08), lineWidth: 1)
            )
        }
    }

    private func sourceCoverageMeter(
        title: String,
        coverage: BrainSourceCoverage,
        systemImage: String
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: systemImage)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Palette.accent)
                    .frame(width: 18)
                Text(title)
                    .font(Typography.labelSmall.weight(.semibold))
                    .foregroundStyle(Palette.textPrimary)
                Spacer()
                Text("\(coverage.organized)/\(coverage.total)")
                    .font(Typography.labelSmall.weight(.semibold))
                    .foregroundStyle(Palette.textSecondary)
            }

            GeometryReader { geometry in
                let total = max(coverage.total, 1)
                let organizedWidth = geometry.size.width * CGFloat(coverage.organized) / CGFloat(total)
                let summarizedWidth = geometry.size.width * CGFloat(coverage.summarized) / CGFloat(total)
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.06))
                    Capsule()
                        .fill(Palette.accent.opacity(0.20))
                        .frame(width: summarizedWidth)
                    Capsule()
                        .fill(Palette.accent.opacity(0.75))
                        .frame(width: organizedWidth)
                }
            }
            .frame(height: 6)

            Text(t(
                "\(coverage.summarized) summarized · \(coverage.organized) linked · \(coverage.unorganized) not linked",
                "\(coverage.summarized) summary · \(coverage.organized) связано · \(coverage.unorganized) без связей"
            ))
            .font(Typography.labelSmall)
            .foregroundStyle(Palette.textSecondary)
            .lineLimit(1)
        }
        .padding(Spacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func brainOverviewSourceRow(_ source: BrainOverviewSource) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: source.sourceKind == "recording" ? "waveform" : "doc.text")
                .font(.system(size: 11))
                .foregroundStyle(source.entityCount > 0 ? Palette.accent : Palette.textTertiary)
                .frame(width: 16)
            VStack(alignment: .leading, spacing: 1) {
                Text(source.title)
                    .font(Typography.bodySmall.weight(.medium))
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                Text(brainOverviewSourceDetail(source))
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(Spacing.xs)
        .background(Color.primary.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func unlinkedBrainSourceRow(_ source: BrainOverviewSource) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: source.sourceKind == "recording" ? "waveform" : "doc.text")
                .font(.system(size: 11))
                .foregroundStyle(Palette.textTertiary)
                .frame(width: 16)
            VStack(alignment: .leading, spacing: 1) {
                Text(source.title)
                    .font(Typography.bodySmall.weight(.medium))
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                Text(t("In Inbox · not in Brain yet", "В инбоксе · ещё не в Мозге"))
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(Spacing.xs)
        .background(Color.primary.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func brainOverviewEntityRow(_ entity: BrainOverviewEntity) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: entityIcon(entity.type))
                .font(.system(size: 11))
                .foregroundStyle(Palette.accent)
                .frame(width: 16)
            VStack(alignment: .leading, spacing: 1) {
                Text(entity.name)
                    .font(Typography.bodySmall.weight(.medium))
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                Text(t(
                    "\(entity.sourceCount) sources · \(entity.recordingCount) voice · \(entity.materialCount) material",
                    "\(entity.sourceCount) источн. · голос: \(entity.recordingCount) · материалы: \(entity.materialCount)"
                ))
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(Spacing.xs)
        .background(Color.primary.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func brainCoverageSummary(_ overview: BrainOverview) -> String {
        let totalSources = overview.recordings.total + overview.materials.total
        let organizedSources = overview.recordings.organized + overview.materials.organized
        let unorganizedSources = overview.recordings.unorganized + overview.materials.unorganized
        if totalSources == 0 {
            return t(
                "Brain is waiting for recordings and materials.",
                "Мозг ждёт записи и материалы."
            )
        }
        if unorganizedSources > 0 {
            return t(
                "\(organizedSources) of \(totalSources) sources are linked into the mirror; \(unorganizedSources) still need entities.",
                "\(organizedSources) из \(totalSources) источн. связаны в зеркало; без сущностей: \(unorganizedSources)."
            )
        }
        return t(
            "All \(totalSources) sources are linked into the mirror.",
            "Все источники связаны в зеркало: \(totalSources)."
        )
    }

    private func brainUnlinkedSourceCount(_ overview: BrainOverview) -> Int {
        overview.recordings.unorganized + overview.materials.unorganized
    }

    private func brainUnlinkedRecentSources(_ overview: BrainOverview) -> [BrainOverviewSource] {
        Array(overview.recentSources.filter { $0.entityCount == 0 }.prefix(4))
    }

    private func brainLinkedRecentSources(_ overview: BrainOverview) -> [BrainOverviewSource] {
        Array(overview.recentSources.filter { $0.entityCount > 0 }.prefix(5))
    }

    private func brainOverviewTotalSources(_ overview: BrainOverview?) -> Int {
        guard let overview else { return 0 }
        return overview.recordings.total + overview.materials.total
    }

    private func brainOverviewSourceDetail(_ source: BrainOverviewSource) -> String {
        if source.entityCount == 0 {
            return sourceKindLabel(source.sourceKind) + " · " + t("not linked yet", "пока без связей")
        }
        return sourceKindLabel(source.sourceKind) + " · \(source.entityCount) "
            + t("linked node(s)", "связанных узл.")
    }

    private func brainAskSection(_ projection: BrainMapProjection) -> some View {
        let suggestions = askSuggestions(for: projection)
        return VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                Text(t("Ask Brain", "Спросить мозг"))
                    .font(Typography.headingSmall)
                Spacer()
                if let answer = model.brainAnswer {
                    Text(answerFreshnessText(answer))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                }
            }

            HStack(alignment: .top, spacing: Spacing.sm) {
                TextField(
                    t(
                        "What changed? What is blocked? Who owns the next step?",
                        "Что изменилось? Что блокирует? Кто отвечает за следующий шаг?"
                    ),
                    text: $model.brainQuestion,
                    axis: .vertical
                )
                .textFieldStyle(.roundedBorder)
                .lineLimit(2)
                .onSubmit { Task { await model.askBrain() } }

                VStack(spacing: Spacing.xs) {
                    Button {
                        Task { await model.askBrain() }
                    } label: {
                        Text(model.askingBrain ? t("Asking", "Спрашиваю") : t("Ask", "Спросить"))
                            .frame(minWidth: 86)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.brainQuestion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.askingBrain)

                    Button {
                        Task { await model.createLens(promptOverride: model.brainQuestion) }
                    } label: {
                        Text(model.creatingLens ? t("Mapping", "Строю") : t("Map it", "Карта"))
                            .frame(minWidth: 86)
                    }
                    .buttonStyle(.bordered)
                    .disabled(model.brainQuestion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.creatingLens)
                }
            }

            if !suggestions.isEmpty {
                LazyVGrid(
                    columns: [
                        GridItem(.flexible(), spacing: Spacing.xs),
                        GridItem(.flexible(), spacing: Spacing.xs),
                        GridItem(.flexible(), spacing: Spacing.xs)
                    ],
                    alignment: .leading,
                    spacing: Spacing.xs
                ) {
                    ForEach(suggestions.prefix(3), id: \.self) { question in
                        Button {
                            Task { await model.askBrain(questionOverride: question) }
                        } label: {
                            Text(question)
                                .font(Typography.labelSmall)
                                .foregroundStyle(Palette.textSecondary)
                                .lineLimit(2)
                                .frame(maxWidth: .infinity, minHeight: 40, alignment: .topLeading)
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
                Text(error)
                    .font(Typography.labelSmall)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let answer = model.brainAnswer {
                brainAnswerView(answer)
            }
        }
        .padding(Spacing.md)
        .background(Color.primary.opacity(0.035))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.primary.opacity(0.08), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func brainAnswerView(_ answer: BrainAnswer) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            if !answer.answer.isEmpty {
                Text(answer.answer)
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if !answer.citations.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: Spacing.xs) {
                        ForEach(answer.citations) { citation in
                            Button {
                                openSource(kind: citation.sourceKind, id: citation.sourceId)
                            } label: {
                                Label(brainCitationLabel(citation), systemImage: citation.sourceKind == "recording" ? "waveform" : "doc.text")
                                    .font(Typography.labelSmall)
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                }
            }

            if !answer.gaps.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    Text(t("Gaps", "Пробелы"))
                        .font(Typography.labelSmall.weight(.semibold))
                        .foregroundStyle(Palette.textSecondary)
                    ForEach(answer.gaps, id: \.self) { gap in
                        Text(gap)
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.textSecondary)
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

    private func mirrorFocusSurface(_ projection: BrainMapProjection) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .top, spacing: Spacing.lg) {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(t("Focus diagrams", "Фокусные диаграммы"))
                        .font(Typography.headingSmall)
                    Text(mirrorFocusSummary(projection))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    Text("\(projection.citations.count)")
                        .font(Typography.headingSmall)
                    Text(t("sources", "источн."))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                }
            }

            LazyVGrid(
                columns: [
                    GridItem(.flexible(), spacing: Spacing.sm),
                    GridItem(.flexible(), spacing: Spacing.sm)
                ],
                alignment: .leading,
                spacing: Spacing.sm
            ) {
                diagramTemplateButton(
                    title: t("Projects", "Проекты"),
                    subtitle: t("owners, risks, next steps", "ответственные, риски, шаги"),
                    icon: "folder.badge.gearshape",
                    prompt: t(
                        "Map my active projects with owners, risks, decisions, and next steps",
                        "Сделай карту активных проектов: ответственные, риски, решения и следующие шаги"
                    )
                )
                diagramTemplateButton(
                    title: t("Decisions", "Решения"),
                    subtitle: t("options, tradeoffs, blockers", "варианты, компромиссы, блокеры"),
                    icon: "checklist",
                    prompt: t(
                        "Map recent decisions with options, tradeoffs, blockers, and open questions",
                        "Сделай карту последних решений: варианты, компромиссы, блокеры и открытые вопросы"
                    )
                )
                diagramTemplateButton(
                    title: t("Relationships", "Связи"),
                    subtitle: t("people, projects, sources", "люди, проекты, источники"),
                    icon: "point.3.connected.trianglepath.dotted",
                    prompt: t(
                        "Map people, projects, and relationships that matter right now",
                        "Сделай карту людей, проектов и связей, которые сейчас важны"
                    )
                )
                diagramTemplateButton(
                    title: t("Timeline", "Хронология"),
                    subtitle: t("what changed and when", "что изменилось и когда"),
                    icon: "calendar.badge.clock",
                    prompt: t(
                        "Create a timeline of the important changes, commitments, and deadlines",
                        "Сделай хронологию важных изменений, обещаний и дедлайнов"
                    )
                )
            }
        }
        .padding(Spacing.md)
        .frame(maxWidth: .infinity, minHeight: 300, alignment: .topLeading)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.primary.opacity(0.035))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }

    private func generatedMapSurface(_ projection: BrainMapProjection) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            if let revision = model.activeMap?.currentRevision {
                generatedLiveStatus(revision, projection: projection)
            }
            if let briefing = projection.briefing {
                generatedBriefing(briefing, projection: projection)
                generatedDiagramPreview(projection)
                generatedEvidence(briefing)
            } else {
                generatedDiagramPreview(projection)
                mapCitationList(projection.citations.prefix(4).map { $0 })
            }
        }
    }

    private func generatedLiveStatus(
        _ revision: BrainMapRevision,
        projection: BrainMapProjection
    ) -> some View {
        let isRefreshing = model.refreshingMapId == model.activeMap?.id
        let title: String
        if isRefreshing {
            title = t("Checking latest sources", "Проверяю новые источники")
        } else if revision.diff.changed {
            title = t("Updated from sources", "Обновлено из источников")
        } else {
            title = t("No source changes", "Источники не изменились")
        }
        let detail: String
        if revision.diff.changed {
            detail = t(
                "\(mapChangeDetail(revision.diff)) since last refresh.",
                "\(mapChangeDetail(revision.diff)) с последнего обновления."
            )
        } else {
            detail = t(
                "This diagram matched the latest source set.",
                "Диаграмма совпала с последним набором источников."
            )
        }

        return VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(alignment: .top, spacing: Spacing.sm) {
                Image(systemName: isRefreshing ? "arrow.triangle.2.circlepath" : "checkmark.seal")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Palette.accent)
                    .frame(width: 24, height: 24)
                    .background(Palette.accentSubtle)
                    .clipShape(RoundedRectangle(cornerRadius: 6))

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(Typography.bodySmall.weight(.semibold))
                        .foregroundStyle(Palette.textPrimary)
                    Text(detail)
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Text(t("rev \(revision.revisionIndex)", "рев. \(revision.revisionIndex)"))
                    .font(Typography.labelSmall.weight(.semibold))
                    .foregroundStyle(Palette.textTertiary)
                    .padding(.horizontal, Spacing.xs)
                    .padding(.vertical, 3)
                    .background(Color.primary.opacity(0.045))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }

            HStack(alignment: .top, spacing: Spacing.sm) {
                liveStatusMetric(
                    value: mapChangeDetail(revision.diff),
                    label: t("change", "изменения"),
                    systemImage: "arrow.triangle.2.circlepath"
                )
                liveStatusMetric(
                    value: mapFreshnessLabel(revision.freshness),
                    label: t("freshness", "свежесть"),
                    systemImage: "clock"
                )
                liveStatusMetric(
                    value: mapWatchText(revision, projection: projection),
                    label: t("watch next", "что проверить"),
                    systemImage: "eye"
                )
            }
        }
        .padding(Spacing.sm)
        .background(revision.freshness.stale ? Color.red.opacity(0.08) : Palette.accentSubtle)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(
                    revision.freshness.stale ? Color.red.opacity(0.22) : Palette.accent.opacity(0.16),
                    lineWidth: 1
                )
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func liveStatusMetric(
        value: String,
        label: String,
        systemImage: String
    ) -> some View {
        HStack(alignment: .top, spacing: Spacing.xs) {
            Image(systemName: systemImage)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Palette.accent)
                .frame(width: 16)
            VStack(alignment: .leading, spacing: 1) {
                Text(value)
                    .font(Typography.labelSmall.weight(.semibold))
                    .foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(label)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, Spacing.xs)
        .background(Color.primary.opacity(0.045))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func generatedDiagramPreview(_ projection: BrainMapProjection) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                Text(t("Diagram preview", "Превью диаграммы"))
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)
                Spacer()
                Text("\(projection.nodes.count) \(t("cards", "карточек")) · \(projection.edges.count) \(t("links", "связей"))")
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
            MacBrainMapCanvasView(
                projection: projection,
                layout: model.activeMap?.layout,
                onOpenSource: openSource,
                onOpenEntity: { id, name in model.openEntity(id: id, name: name) },
                compact: true
            )
            .frame(height: 310)
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
    }

    private func generatedBriefing(
        _ briefing: BrainMapBriefing,
        projection: BrainMapProjection
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(alignment: .top, spacing: Spacing.md) {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(mapTypeLabel(projection.mapType))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                    Text(briefingFocusNote(briefing))
                        .font(Typography.bodySmall.weight(.semibold))
                        .foregroundStyle(Palette.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(briefingFreshnessNote(projection))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                }
                Spacer()
                HStack(spacing: Spacing.xs) {
                    if let openWai = onOpenWai, let space = model.selectedSpace {
                        Button {
                            openWai(space)
                        } label: {
                            Label(t("Ask Wai", "Спросить Wai"), systemImage: "sparkles")
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }

            HStack(spacing: Spacing.sm) {
                coverageTile(
                    value: "\(briefing.coverage.visibleSources)/\(briefing.coverage.totalSources)",
                    label: t("sources in focus", "источн. в фокусе"),
                    systemImage: "doc.text.magnifyingglass"
                )
                coverageTile(
                    value: "\(briefing.coverage.visibleEntities)/\(briefing.coverage.totalEntities)",
                    label: t("nodes in focus", "узлов в фокусе"),
                    systemImage: "point.3.connected.trianglepath.dotted"
                )
                if hiddenFocusCount(briefing) > 0 {
                    coverageTile(
                        value: "\(hiddenFocusCount(briefing))",
                        label: t("kept outside canvas", "вне canvas"),
                        systemImage: "rectangle.stack"
                    )
                }
            }

            mapCoverageLedger(briefing)
        }
        .padding(.bottom, Spacing.xs)
    }

    private func mapCoverageLedger(_ briefing: BrainMapBriefing) -> some View {
        let hiddenSources = max(0, briefing.coverage.totalSources - briefing.coverage.visibleSources)
        let hiddenEntities = max(0, briefing.coverage.totalEntities - briefing.coverage.visibleEntities)
        return VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(alignment: .top, spacing: Spacing.md) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(t("Coverage ledger", "Покрытие"))
                        .font(Typography.labelSmall.weight(.semibold))
                        .foregroundStyle(Palette.accent)
                    Text(loadedMapCoverageText(briefing))
                        .font(Typography.bodySmall.weight(.semibold))
                        .foregroundStyle(Palette.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(hiddenSources > 0 || hiddenEntities > 0
                        ? t(
                            "The canvas stays focused; hidden sources remain in the evidence list.",
                            "Canvas остаётся сфокусированным; скрытые источники остаются в списке доказательств."
                        )
                        : t(
                            "Everything loaded for this map is visible.",
                            "Всё загруженное для этой карты видно."
                        ))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }

            HStack(spacing: Spacing.sm) {
                coverageTile(
                    value: "\(briefing.coverage.totalSources)",
                    label: t("loaded in map", "загружено"),
                    systemImage: "tray.full"
                )
                coverageTile(
                    value: "\(briefing.coverage.visibleSources)",
                    label: t("source cards shown", "карточек источн."),
                    systemImage: "rectangle.stack"
                )
                coverageTile(
                    value: "\(hiddenSources)",
                    label: t("sources evidence-only", "источн. вне canvas"),
                    systemImage: "list.bullet.rectangle"
                )
                if let overview = model.brainOverview, brainOverviewTotalSources(overview) > 0 {
                    coverageTile(
                        value: "\(overview.recordings.total)/\(overview.materials.total)",
                        label: t("voice/materials", "голос/материалы"),
                        systemImage: "waveform"
                    )
                }
            }
        }
        .padding(Spacing.sm)
        .background(Palette.surfaceSubtle)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.primary.opacity(0.08), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func coverageTile(value: String, label: String, systemImage: String) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: systemImage)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Palette.accent)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 1) {
                Text(value)
                    .font(Typography.bodySmall.weight(.semibold))
                    .foregroundStyle(Palette.textPrimary)
                Text(label)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, Spacing.xs)
        .background(Color.primary.opacity(0.045))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func generatedEvidence(_ briefing: BrainMapBriefing) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(alignment: .top, spacing: Spacing.lg) {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(t("Evidence", "Источники"))
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                    if briefing.topSources.isEmpty {
                        wikiEmpty(t("No matching sources yet.", "Подходящих источников пока нет."))
                    } else {
                        mapBriefingSourceList(briefing.topSources, totalSources: briefing.coverage.totalSources)
                    }
                }
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(t("Key nodes", "Ключевые узлы"))
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                    if briefing.topEntities.isEmpty {
                        wikiEmpty(t("No linked pages yet.", "Связанных страниц пока нет."))
                    } else {
                        mapBriefingEntityList(briefing.topEntities)
                    }
                }
            }
        }
    }

    private func mapBriefingSourceList(_ sources: [BrainMapBriefingSource], totalSources: Int) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            ForEach(sources.prefix(12)) { source in
                Button {
                    openSource(kind: source.sourceKind, id: source.sourceId)
                } label: {
                    mapSourceRow(
                        title: source.title,
                        detail: sourceKindLabel(source.sourceKind),
                        systemImage: source.sourceKind == "recording" ? "waveform" : "doc.text"
                    )
                }
                .buttonStyle(.plain)
            }
            if totalSources > sources.prefix(12).count {
                Text(t(
                    "Showing \(sources.prefix(12).count) of \(totalSources) loaded sources.",
                    "Показано \(sources.prefix(12).count) из \(totalSources) загруженных источн."
                ))
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    private func mapBriefingEntityList(_ entities: [BrainMapBriefingEntity]) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            ForEach(entities.prefix(5)) { entity in
                Button {
                    model.openEntity(id: entity.id, name: entity.name)
                } label: {
                    mapSourceRow(
                        title: entity.name,
                        detail: "\(entityTypeLabel(entity.type)) · \(entity.citationCount) "
                            + t("source(s)", "источн."),
                        systemImage: entityIcon(entity.type)
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func mapCitationList(_ citations: [BrainMapCitation]) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(t("Evidence", "Источники"))
                .font(Typography.label)
                .foregroundStyle(Palette.textSecondary)
            ForEach(citations) { citation in
                Button {
                    openSource(kind: citation.sourceKind, id: citation.sourceId)
                } label: {
                    mapSourceRow(
                        title: citation.title,
                        detail: sourceKindLabel(citation.sourceKind),
                        systemImage: citation.sourceKind == "recording" ? "waveform" : "doc.text"
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func mapSourceRow(title: String, detail: String, systemImage: String) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: systemImage)
                .font(.system(size: 11))
                .foregroundStyle(Palette.accent)
                .frame(width: 16)
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(Typography.bodySmall.weight(.medium))
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                Text(detail)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(Spacing.xs)
        .background(Color.primary.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func briefingFocusNote(_ briefing: BrainMapBriefing) -> String {
        if briefing.mode == "empty" {
            return t("No matching evidence yet.", "Подходящих источников пока нет.")
        }
        if briefing.mode == "focused" {
            return t(
                "Showing \(briefing.coverage.visibleSources) of \(briefing.coverage.totalSources) sources and \(briefing.coverage.visibleEntities) of \(briefing.coverage.totalEntities) nodes.",
                "Показано \(briefing.coverage.visibleSources) из \(briefing.coverage.totalSources) источн. и \(briefing.coverage.visibleEntities) из \(briefing.coverage.totalEntities) узлов."
            )
        }
        return t(
            "Showing all \(briefing.coverage.totalSources) sources and \(briefing.coverage.totalEntities) nodes.",
            "Показаны все источники: \(briefing.coverage.totalSources), узлы: \(briefing.coverage.totalEntities)."
        )
    }

    private func briefingFreshnessNote(_ projection: BrainMapProjection) -> String {
        if projection.freshness.stale, let weeks = projection.freshness.weeksSince {
            return t(
                "Newest evidence is \(weeks) week(s) old.",
                "Самому новому источнику \(weeks) нед."
            )
        }
        if projection.freshness.newestSourceAt == nil {
            return t("No dated source yet.", "Пока нет источника с датой.")
        }
        return t("Evidence is current.", "Источники актуальны.")
    }

    private func hiddenFocusCount(_ briefing: BrainMapBriefing) -> Int {
        max(0, briefing.coverage.totalSources - briefing.coverage.visibleSources)
            + max(0, briefing.coverage.totalEntities - briefing.coverage.visibleEntities)
    }

    private func sourceWord(_ count: Int) -> String {
        if count == 1 {
            return t("source", "источн.")
        }
        return t("sources", "источн.")
    }

    private func loadedMapCoverageText(_ briefing: BrainMapBriefing) -> String {
        let wholeBrainTotal = brainOverviewTotalSources(model.brainOverview)
        if wholeBrainTotal > briefing.coverage.totalSources {
            return t(
                "\(briefing.coverage.totalSources) \(sourceWord(briefing.coverage.totalSources)) loaded into this map from \(wholeBrainTotal) sources in Wai Brain.",
                "\(briefing.coverage.totalSources) \(sourceWord(briefing.coverage.totalSources)) загружено в карту из \(wholeBrainTotal) источн. в Wai Brain."
            )
        }
        return t(
            "\(briefing.coverage.totalSources) \(sourceWord(briefing.coverage.totalSources)) loaded into this map.",
            "\(briefing.coverage.totalSources) \(sourceWord(briefing.coverage.totalSources)) загружено в карту."
        )
    }

    private func localizedSuggestedQuestions(
        mapType: String,
        fallback: [String]
    ) -> [String] {
        switch mapType {
        case "decision":
            return [
                t("What changed since this decision?", "Что изменилось после этого решения?"),
                t("Which sources disagree or add risk?", "Какие источники спорят или добавляют риск?"),
                t("What is still open?", "Что ещё открыто?")
            ]
        case "timeline":
            return [
                t("What changed most recently?", "Что изменилось недавно?"),
                t("Which deadlines or commitments are implied?", "Какие дедлайны или обещания следуют из этого?"),
                t("What has not been updated in a while?", "Что давно не обновлялось?")
            ]
        case "relationship":
            return [
                t("Who is connected to this work?", "Кто связан с этой работой?"),
                t("Which relationship has the strongest evidence?", "Какая связь подтверждена сильнее всего?"),
                t("Where are the missing links?", "Где не хватает связей?")
            ]
        case "comparison":
            return [
                t("What are the strongest differences?", "Какие различия самые сильные?"),
                t("Which option has the best evidence?", "У какого варианта лучшие доказательства?"),
                t("What evidence is missing before choosing?", "Каких источников не хватает для выбора?")
            ]
        case "open_questions":
            return [
                t("Which question blocks progress?", "Какой вопрос блокирует прогресс?"),
                t("Who or what source can answer it?", "Кто или какой источник может ответить?"),
                t("What should Wai watch for next?", "За чем Wai следить дальше?")
            ]
        default:
            let localized = [
                t("What are the active risks?", "Какие сейчас активные риски?"),
                t("What changed since the last update?", "Что изменилось с последнего обновления?"),
                t("What should happen next?", "Что должно произойти дальше?")
            ]
            return fallback.isEmpty ? localized : fallback
        }
    }

    private func askSuggestions(for projection: BrainMapProjection) -> [String] {
        localizedSuggestedQuestions(
            mapType: projection.mapType,
            fallback: projection.briefing?.suggestedQuestions ?? []
        )
    }

    private func answerFreshnessText(_ answer: BrainAnswer) -> String {
        if answer.freshness.stale, let weeks = answer.freshness.weeksSince {
            return t(
                "Newest evidence is \(weeks) week(s) old.",
                "Самому новому источнику \(weeks) нед."
            )
        }
        if answer.freshness.newestSourceAt == nil {
            return t("No dated source.", "Нет источника с датой.")
        }
        return t("Evidence is current.", "Источники актуальны.")
    }

    private func brainCitationLabel(_ citation: BrainAnswerCitation) -> String {
        let title = citation.title?.trimmingCharacters(in: .whitespacesAndNewlines)
        let base = (title?.isEmpty == false ? title : nil) ?? sourceKindLabel(citation.sourceKind)
        guard let startMs = citation.startMs, citation.sourceKind == "recording" else {
            return base
        }
        return "\(base) · \(timecode(milliseconds: startMs))"
    }

    private func timecode(milliseconds: Int) -> String {
        let seconds = max(0, milliseconds / 1000)
        return "\(seconds / 60):\(String(format: "%02d", seconds % 60))"
    }

    private func mapTypeLabel(_ mapType: String) -> String {
        switch mapType {
        case "live_mirror": return t("Live Mirror", "Живое зеркало")
        case "project_state": return t("Project state", "Состояние проекта")
        case "decision": return t("Decision", "Решение")
        case "relationship": return t("Relationships", "Связи")
        case "timeline": return t("Timeline", "Хронология")
        case "comparison": return t("Comparison", "Сравнение")
        case "open_questions": return t("Open questions", "Открытые вопросы")
        default: return mapType.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    private func entityTypeLabel(_ type: String) -> String {
        switch type {
        case "person": return t("person", "человек")
        case "project": return t("project", "проект")
        case "organization": return t("organization", "организация")
        case "topic": return t("topic", "тема")
        default: return type
        }
    }

    private func diagramTemplateButton(
        title: String,
        subtitle: String,
        icon: String,
        prompt: String
    ) -> some View {
        Button {
            model.lensPrompt = prompt
            showLensForm = true
        } label: {
            HStack(alignment: .top, spacing: Spacing.sm) {
                Image(systemName: icon)
                    .foregroundStyle(Palette.accent)
                    .frame(width: 22)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(Typography.bodySmall.weight(.semibold))
                        .foregroundStyle(Palette.textPrimary)
                    Text(subtitle)
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(Spacing.sm)
            .frame(maxWidth: .infinity, minHeight: 72, alignment: .topLeading)
            .background(Palette.surfaceSubtle)
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color.primary.opacity(0.08), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }

    private func mirrorFocusSummary(_ projection: BrainMapProjection) -> String {
        let hiddenSources = projection.stats?["hidden_source_count"] ?? 0
        let hiddenEntities = projection.stats?["hidden_entity_count"] ?? 0
        if hiddenSources > 0 || hiddenEntities > 0 {
            return t(
                "\(projection.citations.count) sources · \(hiddenSources + hiddenEntities) outside focus",
                "\(projection.citations.count) источн. · вне фокуса: \(hiddenSources + hiddenEntities)"
            )
        }
        return t(
            "\(projection.citations.count) sources · \(projection.nodes.count) cards",
            "\(projection.citations.count) источн. · \(projection.nodes.count) карточек"
        )
    }

    private var mapStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Spacing.xs) {
                mapSelector(
                    id: "mirror",
                    title: t("Live Mirror", "Живое зеркало"),
                    detail: t("always current", "всегда актуально"),
                    subdetail: t("updates from sources", "обновляется из источников")
                )
                ForEach(model.maps) { map in
                    mapSelector(
                        id: map.id,
                        title: map.title,
                        detail: "\(mapOriginLabel(map.origin)) · \(mapSourceCountText(map.currentRevision))",
                        subdetail: "\(diffSummary(map.currentRevision?.diff)) · \(mapCheckedText(map.currentRevision))"
                    )
                }
            }
        }
    }

    private func mapSelector(
        id: String,
        title: String,
        detail: String,
        subdetail: String? = nil
    ) -> some View {
        let active = model.selectedMapId == id
        return Button {
            model.selectedMapId = id
        } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(Typography.labelSmall.weight(.semibold))
                    .lineLimit(1)
                Text(detail)
                    .font(Typography.labelSmall)
                    .foregroundStyle(active ? Palette.textSecondary : Palette.textTertiary)
                    .lineLimit(1)
                if let subdetail {
                    Text(subdetail)
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                        .lineLimit(1)
                }
            }
            .frame(width: 184, alignment: .leading)
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, Spacing.xs)
            .background(active ? Palette.accentSubtle : Color.primary.opacity(0.045))
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }

    private func mapStats(_ projection: BrainMapProjection) -> some View {
        HStack(spacing: Spacing.sm) {
            metricPill("\(projection.nodes.count)", t("cards", "карточек"))
            metricPill("\(projection.edges.count)", t("links", "связей"))
            metricPill("\(projection.citations.count)", t("sources", "источн."))
            if projection.freshness.stale, let weeks = projection.freshness.weeksSince {
                metricPill("\(weeks)", t("weeks since newest source", "нед. с нового источника"))
            }
            Spacer()
        }
    }

    private func metricPill(_ value: String, _ label: String) -> some View {
        HStack(spacing: 5) {
            Text(value).font(Typography.labelSmall.weight(.semibold))
            Text(label).font(Typography.labelSmall)
        }
        .foregroundStyle(Palette.textSecondary)
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, 5)
        .background(Color.primary.opacity(0.045))
        .clipShape(RoundedRectangle(cornerRadius: 7))
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

    private func signedChange(
        added: Int,
        removed: Int,
        label: String,
        labelRu: String
    ) -> String? {
        if added == 0 && removed == 0 { return nil }
        let textLabel = t(label, labelRu)
        if removed == 0 { return "+\(added) \(textLabel)" }
        if added == 0 { return "-\(removed) \(textLabel)" }
        return "+\(added) / -\(removed) \(textLabel)"
    }

    private func mapChangeDetail(_ diff: BrainMapDiff?) -> String {
        guard let diff else { return t("No refresh yet", "Ещё не обновлялось") }
        let parts = [
            signedChange(added: diff.sourcesAdded, removed: diff.sourcesRemoved, label: "sources", labelRu: "источн."),
            signedChange(added: diff.nodesAdded, removed: diff.nodesRemoved, label: "cards", labelRu: "карточек"),
            signedChange(added: diff.edgesAdded, removed: diff.edgesRemoved, label: "links", labelRu: "связей")
        ].compactMap { $0 }
        if !parts.isEmpty { return parts.joined(separator: " · ") }
        return t("No source changes", "Источники не изменились")
    }

    private func mapFreshnessLabel(_ freshness: BrainMapFreshness) -> String {
        if let weeks = freshness.weeksSince {
            if weeks == 0 {
                return t("Newest source this week", "Новый источник на этой неделе")
            }
            return t("Newest source \(weeks) weeks old", "Новейшему источнику \(weeks) нед.")
        }
        if freshness.newestSourceAt == nil {
            return t("No dated source", "Нет источника с датой")
        }
        return t("Current source set", "Актуальный набор источников")
    }

    private func mapWatchText(
        _ revision: BrainMapRevision,
        projection: BrainMapProjection
    ) -> String {
        if revision.freshness.stale {
            return t(
                "Ask what changed before relying on it.",
                "Спроси, что изменилось, прежде чем полагаться."
            )
        }
        if revision.diff.changed {
            return t(
                "Review new evidence, then keep the map if it still matches reality.",
                "Проверь новые источники и сохрани карту, если она всё ещё верна."
            )
        }
        if projection.briefing?.mode == "focused" {
            return t(
                "Open the sources list when you need the full picture.",
                "Открой список источников, если нужна полная картина."
            )
        }
        return t(
            "Safe to use for the current source set.",
            "Можно использовать для текущего набора источников."
        )
    }

    // MARK: - Pages

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
                    ? t("Pages appear as Wai finds people, projects, and topics in your recordings.",
                        "Страницы появляются, когда Wai находит людей, проекты и темы в ваших записях.")
                    : t("No pages match.", "Нет совпадений."))
            } else {
                VStack(alignment: .leading, spacing: Spacing.xs) {
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
                    Text(filterLabel(BrainPageFilter(rawValue: entity.type.rawValue) ?? .topic))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
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

    // MARK: - Curated knowledge (demoted)

    @ViewBuilder
    private var curatedDisclosure: some View {
        DisclosureGroup(t("Curated knowledge · Sources", "Подтверждённые знания · Источники")) {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                if model.spaces.count > 1 {
                    HStack {
                        Text(t("Brain", "Мозг")).font(Typography.labelSmall)
                        Picker("", selection: $model.selectedSpaceId) {
                            ForEach(model.spaces) { space in
                                Text(space.name).tag(space.id)
                            }
                        }
                        .labelsHidden()
                        .frame(width: 220)
                    }
                }
                if let error = model.spaceError {
                    Text(error).font(Typography.bodySmall).foregroundStyle(.red)
                }
                reviewSuggestionsSection
                sourcesSection
                advancedSection
            }
            .padding(.top, Spacing.xs)
        }
        .font(Typography.bodySmall)
    }

    @ViewBuilder
    private var reviewSuggestionsSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                Text(t("Review", "Проверка")).font(Typography.label).foregroundStyle(Palette.textSecondary)
                Spacer()
                Text("\(model.spaceReviewPacks.count)")
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
            if model.spaceReviewPacks.isEmpty {
                wikiEmpty(t("Nothing waiting for review.", "Нет знаний на проверку."))
            } else {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(model.spaceReviewPacks) { pack in
                        spaceReviewPackRow(pack)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var sourcesSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                Text(t("Sources", "Источники")).font(Typography.label).foregroundStyle(Palette.textSecondary)
                Spacer()
                if let onOpenInbox {
                    Button(t("Open Inbox", "Открыть инбокс")) { onOpenInbox() }
                        .buttonStyle(.plain)
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.accent)
                }
            }
            if let home = model.spaceHome, !home.sources.isEmpty {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(home.sources) { source in
                        brainSourceRow(source)
                    }
                }
            } else {
                wikiEmpty(t("Add recordings or materials from Inbox.", "Добавьте записи или материалы из инбокса."))
            }
        }
    }

    @ViewBuilder
    private var advancedSection: some View {
        if let home = model.spaceHome {
            HStack(alignment: .top, spacing: Spacing.sm) {
                spaceActionCard(
                    eyebrow: t("Share", "Поделиться"),
                    title: t("Invite teammate", "Пригласить участника"),
                    systemImage: "person.badge.plus"
                ) {
                    TextField(t("teammate@example.com", "email@example.com"), text: $shareEmail)
                        .textFieldStyle(.roundedBorder)
                    HStack(spacing: Spacing.xs) {
                        Picker("", selection: $shareRole) {
                            Text(t("Viewer", "Читатель")).tag("viewer")
                            Text(t("Editor", "Редактор")).tag("editor")
                        }
                        .labelsHidden()
                        Button {
                            Task {
                                await model.shareSelectedSpace(email: shareEmail, role: shareRole)
                                if model.shareMessage != nil { shareEmail = "" }
                            }
                        } label: {
                            Text(model.sharing ? t("Sharing", "Открываю") : t("Share", "Поделиться"))
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.sharing || shareEmail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                    if let message = model.shareMessage {
                        Text(message).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
                    }
                }

                spaceActionCard(
                    eyebrow: t("Export", "Экспорт"),
                    title: t("Export notes", "Экспортировать заметки"),
                    systemImage: "square.and.arrow.up"
                ) {
                    HStack(spacing: Spacing.xs) {
                        ForEach(home.engineProfiles, id: \.self) { profile in
                            Button(exportProfileLabel(profile)) {
                                Task { await model.exportSelectedSpace(profile: profile) }
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                    if let message = model.exportMessage {
                        Text(message).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
                    }
                }
            }

            Text(t("Personal preferences live in Settings → Memory.",
                   "Личные предпочтения — в Настройки → Память."))
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
        }
    }

    private func spaceActionCard<Content: View>(
        eyebrow: String,
        title: String,
        systemImage: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: systemImage)
                    .font(.system(size: 12))
                    .foregroundStyle(Palette.accent)
                Text(eyebrow)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
            }
            Text(title).font(Typography.bodySmall.weight(.semibold))
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func spaceReviewPackRow(_ pack: BrainReviewPack) -> some View {
        let acting = model.actingSpaceReviewPackIds.contains(pack.id)
        return HStack(alignment: .top, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(pack.title).font(Typography.bodySmall.weight(.medium))
                Text(pack.summary)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            HStack(spacing: Spacing.xs) {
                Button {
                    Task { await model.rejectSpaceReviewPack(pack.id) }
                } label: {
                    Text(t("Ignore", "Игнорировать"))
                }
                .buttonStyle(.bordered)
                .disabled(acting)

                Button {
                    Task { await model.acceptSpaceReviewPack(pack.id) }
                } label: {
                    Text(t("Approve", "Подтвердить"))
                }
                .buttonStyle(.borderedProminent)
                .disabled(acting)
            }
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func brainSourceRow(_ source: BrainSpaceSourceSummary) -> some View {
        Button {
            openSource(kind: source.sourceKind, id: source.sourceId)
        } label: {
            HStack(spacing: Spacing.sm) {
                Image(systemName: source.sourceKind == "recording" ? "waveform" : "doc.text")
                    .font(.system(size: 11))
                    .foregroundStyle(Palette.accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(source.sourceTitle ?? t("Untitled source", "Источник без названия"))
                        .font(Typography.bodySmall.weight(.medium))
                        .lineLimit(1)
                    Text(sourceKindLabel(source.sourceKind))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                }
                Spacer()
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
                "Add recordings or materials from Inbox to build your Brain.",
                "Добавьте записи или материалы из инбокса."
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
                    wikiHeader(entity)
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
        guard sourceKind == .recording || sourceKind == .item else { return }
        onOpenSource(InboxDetailRef(kind: sourceKind, id: id))
    }

    private func sourceKindLabel(_ kind: String) -> String {
        switch kind {
        case "recording": return t("recording", "запись")
        case "item": return t("material", "материал")
        default: return kind
        }
    }

    private func exportProfileLabel(_ profile: String) -> String {
        switch profile {
        case "obsidian": return t("Obsidian", "Obsidian")
        case "mempalace": return t("MemPalace", "MemPalace")
        case "gbrain": return t("GBrain", "GBrain")
        default: return t("Export", "Экспорт")
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct MacBrainMapCanvasView: View {
    let projection: BrainMapProjection
    let layout: [String: BrainMapPosition]?
    let onOpenSource: (String, String) -> Void
    let onOpenEntity: (String, String) -> Void
    let compact: Bool

    private var maxSources: Int { compact ? 2 : 3 }
    private var maxEntities: Int { compact ? 5 : 8 }
    private var maxGaps: Int { compact ? 0 : 1 }

    private var displayNodes: [BrainMapNode] {
        let lens = projection.nodes.filter { $0.kind == "lens" }.prefix(1)
        let sources = projection.nodes.filter { $0.kind == "source" }.prefix(maxSources)
        let entities = projection.nodes
            .filter { $0.kind == "entity" }
            .sorted {
                if $0.citationIds.count != $1.citationIds.count {
                    return $0.citationIds.count > $1.citationIds.count
                }
                return $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending
            }
            .prefix(maxEntities)
        let gaps = projection.nodes.filter { $0.kind == "gap" }.prefix(maxGaps)
        return Array(lens) + Array(sources) + Array(entities) + Array(gaps)
    }

    private var displayNodeIds: Set<String> {
        Set(displayNodes.map(\.id))
    }

    private var displayEdges: [BrainMapEdge] {
        projection.edges
            .filter { displayNodeIds.contains($0.source) && displayNodeIds.contains($0.target) }
            .prefix(18)
            .map { $0 }
    }

    var body: some View {
        GeometryReader { geometry in
            let positions = fittedPositions(in: geometry.size)
            ZStack {
                Canvas { context, _ in
                    for edge in displayEdges {
                        guard let source = positions[edge.source], let target = positions[edge.target] else { continue }
                        var path = Path()
                        path.move(to: source)
                        path.addCurve(
                            to: target,
                            control1: CGPoint(x: source.x + 90, y: source.y),
                            control2: CGPoint(x: target.x - 90, y: target.y)
                        )
                        context.stroke(
                            path,
                            with: .color(edgeColor(edge).opacity(0.58)),
                            lineWidth: edge.kind == "supports" ? 1.8 : 1.2
                        )
                    }
                }

                ForEach(displayNodes) { node in
                    if let position = positions[node.id] {
                        Button {
                            open(node)
                        } label: {
                            nodeCard(node)
                        }
                        .buttonStyle(.plain)
                        .disabled(!isOpenable(node))
                        .position(position)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.primary.opacity(0.035))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color.primary.opacity(0.08), lineWidth: 1)
            )
        }
    }

    private func nodeCard(_ node: BrainMapNode) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 5) {
                Circle()
                    .fill(nodeColor(node.kind))
                    .frame(width: 7, height: 7)
                Text(node.kind.replacingOccurrences(of: "_", with: " ").uppercased())
                    .font(.system(size: compact ? 8 : 9, weight: .semibold))
                    .foregroundStyle(Palette.textTertiary)
            }
            Text(node.title)
                .font(compact ? Typography.labelSmall.weight(.semibold) : Typography.bodySmall.weight(.semibold))
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(compact ? 1 : (node.kind == "lens" ? 2 : 1))
                .truncationMode(.tail)
            if !compact, let body = node.body, !body.isEmpty {
                Text(body)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(node.kind == "lens" ? 2 : 1)
            }
            if !compact, !node.citationIds.isEmpty {
                Text("\(node.citationIds.count) source\(node.citationIds.count == 1 ? "" : "s")")
                    .font(.system(size: 10, weight: .medium))
                .foregroundStyle(Palette.accent)
            }
        }
        .frame(width: node.kind == "lens" ? (compact ? 190 : 210) : (compact ? 142 : 164), alignment: .leading)
        .frame(minHeight: node.kind == "lens" ? (compact ? 58 : 76) : (compact ? 50 : 64), alignment: .leading)
        .padding(compact ? Spacing.xs : Spacing.sm)
        .background(node.kind == "lens" ? Palette.accentSubtle : Palette.surfaceSubtle)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(nodeColor(node.kind).opacity(0.24), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .shadow(color: .black.opacity(0.06), radius: 10, x: 0, y: 5)
    }

    private func fittedPositions(in size: CGSize) -> [String: CGPoint] {
        let nodes = displayNodes
        guard !nodes.isEmpty else { return [:] }
        if !compact, nodes.count <= 6 {
            return fittedPositionsFromSuppliedLayout(in: size)
        }

        let width = max(size.width, compact ? 720 : 760)
        let topY: CGFloat = compact ? 50 : 74
        let rowY: [CGFloat] = compact ? [132, 214, 286] : [170, 260, 350, 440]
        var positions: [String: CGPoint] = [:]
        let lens = nodes.first { $0.kind == "lens" }
        if let lens {
            positions[lens.id] = CGPoint(x: width * 0.50, y: topY)
        }

        let sources = nodes.filter { $0.kind == "source" }
        for (index, node) in sources.enumerated() {
            positions[node.id] = CGPoint(
                x: width * 0.18,
                y: rowY[min(index, rowY.count - 1)]
            )
        }

        let entities = nodes.filter { $0.kind == "entity" }
        let entityXs = compact ? [width * 0.44, width * 0.70] : [width * 0.42, width * 0.64]
        for (index, node) in entities.enumerated() {
            positions[node.id] = CGPoint(
                x: entityXs[index % entityXs.count],
                y: rowY[min(index / entityXs.count, rowY.count - 1)]
            )
        }

        let gaps = nodes.filter { $0.kind == "gap" }
        for (index, node) in gaps.enumerated() {
            positions[node.id] = CGPoint(
                x: width * 0.84,
                y: rowY[min(index + 1, rowY.count - 1)]
            )
        }

        return positions.mapValues { point in
            let horizontalInset: CGFloat = compact ? 76 : 96
            let verticalInset: CGFloat = compact ? 40 : 64
            return CGPoint(
                x: min(max(point.x, horizontalInset), max(horizontalInset, size.width - horizontalInset)),
                y: min(max(point.y, verticalInset), max(verticalInset, size.height - verticalInset))
            )
        }
    }

    private func fittedPositionsFromSuppliedLayout(in size: CGSize) -> [String: CGPoint] {
        let raw = rawPositions()
        guard !raw.isEmpty else { return [:] }
        let minX = raw.values.map(\.x).min() ?? 0
        let maxX = raw.values.map(\.x).max() ?? minX
        let minY = raw.values.map(\.y).min() ?? 0
        let maxY = raw.values.map(\.y).max() ?? minY
        let width = max(1, maxX - minX)
        let height = max(1, maxY - minY)
        let availableWidth = max(1, size.width - 240)
        let availableHeight = max(1, size.height - 140)
        let scale = min(1.0, availableWidth / width, availableHeight / height)
        let centerX = minX + width / 2
        let centerY = minY + height / 2
        return raw.mapValues { point in
            CGPoint(
                x: (point.x - centerX) * scale + size.width / 2,
                y: (point.y - centerY) * scale + size.height / 2
            )
        }
    }

    private func rawPositions() -> [String: CGPoint] {
        var laneCounts: [String: Int] = [:]
        return Dictionary(uniqueKeysWithValues: displayNodes.enumerated().map { index, node in
            if displayNodes.count <= 6 {
                if let persisted = layout?[node.id] {
                    return (node.id, CGPoint(x: persisted.x, y: persisted.y))
                }
                if let supplied = node.position {
                    return (node.id, CGPoint(x: supplied.x, y: supplied.y))
                }
            }
            let lane = node.lane ?? "center"
            let laneIndex = laneCounts[lane, default: 0]
            laneCounts[lane] = laneIndex + 1
            let x: CGFloat
            switch lane {
            case "sources": x = -360
            case "related": x = 360
            default: x = node.kind == "lens" ? 0 : CGFloat((index % 3) - 1) * 220
            }
            let y = node.kind == "lens" ? 0 : CGFloat(-170 + laneIndex * 130)
            return (node.id, CGPoint(x: x, y: y))
        })
    }

    private func isOpenable(_ node: BrainMapNode) -> Bool {
        (node.kind == "source" && node.sourceKind != nil && node.sourceId != nil)
            || (node.kind == "entity" && node.entityId != nil)
    }

    private func open(_ node: BrainMapNode) {
        if node.kind == "source", let kind = node.sourceKind, let id = node.sourceId {
            onOpenSource(kind, id)
        } else if node.kind == "entity", let id = node.entityId {
            onOpenEntity(id, node.title)
        }
    }

    private func nodeColor(_ kind: String) -> Color {
        switch kind {
        case "lens": return Palette.accent
        case "source": return .blue
        case "entity": return .green
        case "gap": return .orange
        default: return Palette.textTertiary
        }
    }

    private func edgeColor(_ edge: BrainMapEdge) -> Color {
        switch edge.kind {
        case "mentions": return Palette.accent
        case "related_to": return Palette.textTertiary
        default: return Palette.textSecondary
        }
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

    // Live mirror + generated maps
    @Published var mirror: BrainMapProjection?
    @Published var brainOverview: BrainOverview?
    @Published var brainSyncResult: BrainSyncResult?
    @Published var maps: [BrainMap] = []
    @Published var selectedMapId = "mirror"
    @Published var lensPrompt = ""
    @Published var creatingLens = false
    @Published var refreshingMapId: String?
    @Published var linkingBrainSources = false
    @Published var brainQuestion = ""
    @Published var brainAnswer: BrainAnswer?
    @Published var askingBrain = false
    @Published var brainAskError: String?

    // Pages (entities)
    @Published var entities: [Entity] = []
    @Published var pageFilter: BrainPageFilter = .all
    @Published var searchText = ""
    @Published var selectedEntity: SelectedEntity?
    @Published var entityPage: EntityPage?
    @Published var pageLoading = false
    @Published var pageError: String?

    // Curated knowledge (Brain spaces)
    @Published var spaces: [BrainSpace] = []
    @Published var selectedSpaceId = ""
    @Published var spaceHome: BrainSpaceHome?
    @Published var spaceReviewPacks: [BrainReviewPack] = []
    @Published var spaceError: String?
    @Published var sharing = false
    @Published var shareMessage: String?
    @Published var exportMessage: String?
    @Published var actingSpaceReviewPackIds: Set<String> = []

    private let apiClient: APIClient
    private var autoRefreshedMapIds: Set<String> = []

    init(apiClient: APIClient, initialMapId: String? = nil) {
        self.apiClient = apiClient
        selectInitialMap(initialMapId)
    }

    func selectInitialMap(_ mapId: String?) {
        guard let mapId, !mapId.isEmpty else { return }
        selectedMapId = mapId
    }

    func load() async {
        loading = true
        errorMessage = nil
        defer { loading = false }
        do {
            // No-fallback: a transient failure must NOT look like "empty brain".
            let loadedSync = try await apiClient.syncBrain(limit: 500)
            async let mirrorRequest = apiClient.getBrainMirror(limit: 60)
            async let graphRequest = apiClient.getBrainGraph(limit: 200)
            async let mapsRequest = apiClient.listBrainMaps(limit: 50)
            async let entitiesRequest = apiClient.listEntities(limit: 200)
            let (loadedMirror, loadedGraph, loadedMaps, loadedEntities) = try await (
                mirrorRequest,
                graphRequest,
                mapsRequest,
                entitiesRequest
            )
            brainSyncResult = loadedSync
            mirror = loadedMirror
            brainOverview = loadedGraph.overview
            maps = loadedMaps.maps
            entities = loadedEntities
            if selectedMapId != "mirror", !maps.contains(where: { $0.id == selectedMapId }) {
                selectedMapId = "mirror"
            }
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        await loadSpaces()
        await loadSelectedSpace()
    }

    func repairBrainLinks() async {
        guard !linkingBrainSources else { return }
        linkingBrainSources = true
        defer { linkingBrainSources = false }
        do {
            let loadedSync = try await apiClient.syncBrain(limit: 500)
            async let mirrorRequest = apiClient.getBrainMirror(limit: 60)
            async let graphRequest = apiClient.getBrainGraph(limit: 200)
            async let mapsRequest = apiClient.listBrainMaps(limit: 50)
            async let entitiesRequest = apiClient.listEntities(limit: 200)
            let (loadedMirror, loadedGraph, loadedMaps, loadedEntities) = try await (
                mirrorRequest,
                graphRequest,
                mapsRequest,
                entitiesRequest
            )
            brainSyncResult = loadedSync
            mirror = loadedMirror
            brainOverview = loadedGraph.overview
            maps = loadedMaps.maps
            entities = loadedEntities
            if selectedMapId != "mirror", !maps.contains(where: { $0.id == selectedMapId }) {
                selectedMapId = "mirror"
            }
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    var activeMap: BrainMap? {
        maps.first { $0.id == selectedMapId }
    }

    var activeProjection: BrainMapProjection? {
        if selectedMapId == "mirror" {
            return mirror
        }
        return activeMap?.currentRevision?.projection
    }

    func createLens(promptOverride: String? = nil) async {
        let prompt = (promptOverride ?? lensPrompt).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty, !creatingLens else { return }
        creatingLens = true
        defer { creatingLens = false }
        do {
            let created = try await apiClient.createBrainMap(
                BrainMapCreateRequest(prompt: prompt, origin: "brain")
            )
            maps.removeAll { $0.id == created.id }
            maps.insert(created, at: 0)
            selectedMapId = created.id
            lensPrompt = ""
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func askBrain(questionOverride: String? = nil) async {
        let question = (questionOverride ?? brainQuestion).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, !askingBrain else { return }
        brainQuestion = question
        askingBrain = true
        defer { askingBrain = false }
        do {
            brainAnswer = try await apiClient.askBrain(question: question)
            brainAskError = nil
        } catch {
            brainAskError = error.localizedDescription
        }
    }

    func refreshActiveMap() async {
        guard let map = activeMap, refreshingMapId == nil else { return }
        refreshingMapId = map.id
        defer { refreshingMapId = nil }
        do {
            _ = try await apiClient.refreshBrainMap(mapId: map.id)
            let refreshed = try await apiClient.getBrainMap(mapId: map.id)
            replaceMap(refreshed)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refreshSelectedMapOnceIfNeeded() async {
        guard let map = activeMap, refreshingMapId == nil else { return }
        guard !autoRefreshedMapIds.contains(map.id) else { return }
        autoRefreshedMapIds.insert(map.id)
        await refreshActiveMap()
    }

    func keepActiveMap() async {
        guard let map = activeMap else { return }
        do {
            let updated = try await apiClient.updateBrainMap(
                mapId: map.id,
                BrainMapUpdateRequest(status: "saved")
            )
            replaceMap(updated)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    var hasAnything: Bool {
        !(mirror?.nodes.isEmpty ?? true)
            || ((brainOverview?.recordings.total ?? 0) + (brainOverview?.materials.total ?? 0)) > 0
            || !maps.isEmpty
            || !entities.isEmpty
            || (spaceHome?.claimCounts.values.reduce(0, +) ?? 0) > 0
            || !spaceReviewPacks.isEmpty
            || !(spaceHome?.sources.isEmpty ?? true)
    }

    var visiblePages: [Entity] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return entities.filter { entity in
            (pageFilter == .all || entity.type.rawValue == pageFilter.rawValue)
                && (query.isEmpty || entity.name.lowercased().contains(query))
        }
    }

    func loadSpaces() async {
        do {
            let response = try await apiClient.listBrainSpaces()
            spaces = response.spaces
            if selectedSpaceId.isEmpty || !response.spaces.contains(where: { $0.id == selectedSpaceId }) {
                selectedSpaceId = response.spaces.first?.id ?? ""
            }
            spaceError = nil
        } catch {
            spaceError = error.localizedDescription
        }
    }

    func loadSelectedSpace() async {
        guard !selectedSpaceId.isEmpty else {
            spaceHome = nil
            spaceReviewPacks = []
            return
        }
        do {
            async let homeRequest = apiClient.getBrainSpaceHome(spaceId: selectedSpaceId)
            async let packsRequest = apiClient.listBrainReviewPacks(spaceId: selectedSpaceId)
            let loadedHome = try await homeRequest
            let loadedPacks = try await packsRequest
            spaceHome = loadedHome
            spaceReviewPacks = loadedPacks.reviewPacks
            spaceError = nil
        } catch {
            spaceError = error.localizedDescription
        }
    }

    func shareSelectedSpace(email: String, role: String) async {
        let trimmedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !selectedSpaceId.isEmpty, !trimmedEmail.isEmpty, !sharing else { return }
        sharing = true
        shareMessage = nil
        defer { sharing = false }
        do {
            _ = try await apiClient.addBrainSpaceMember(
                spaceId: selectedSpaceId,
                email: trimmedEmail,
                role: role
            )
            shareMessage = "Shared with \(trimmedEmail) as \(role)."
            spaceError = nil
        } catch {
            spaceError = error.localizedDescription
        }
    }

    func exportSelectedSpace(profile: String) async {
        guard !selectedSpaceId.isEmpty else { return }
        exportMessage = nil
        do {
            let export = try await apiClient.exportBrainSpace(spaceId: selectedSpaceId, profile: profile)
            switch export.files.count {
            case 0:
                exportMessage = "Nothing to export yet. Approved knowledge notes will appear here."
            case 1:
                exportMessage = "1 Markdown file is ready."
            default:
                exportMessage = "\(export.files.count) Markdown files are ready."
            }
            spaceError = nil
        } catch {
            spaceError = error.localizedDescription
        }
    }

    var selectedSpace: BrainSpace? {
        spaces.first { $0.id == selectedSpaceId }
    }

    private func replaceMap(_ updated: BrainMap) {
        if let index = maps.firstIndex(where: { $0.id == updated.id }) {
            maps[index] = updated
        } else {
            maps.insert(updated, at: 0)
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

    func acceptSpaceReviewPack(_ id: String) async {
        await decideSpaceReviewPack(id) {
            try await self.apiClient.acceptBrainReviewPack(spaceId: self.selectedSpaceId, packId: id)
        }
    }

    func rejectSpaceReviewPack(_ id: String) async {
        await decideSpaceReviewPack(id) {
            try await self.apiClient.rejectBrainReviewPack(spaceId: self.selectedSpaceId, packId: id)
        }
    }

    private func decideSpaceReviewPack(
        _ id: String,
        action: @escaping () async throws -> BrainReviewPack
    ) async {
        guard !selectedSpaceId.isEmpty, !actingSpaceReviewPackIds.contains(id) else { return }
        actingSpaceReviewPackIds.insert(id)
        defer { actingSpaceReviewPackIds.remove(id) }
        do {
            _ = try await action()
            spaceReviewPacks.removeAll { $0.id == id }
            await loadSelectedSpace()
        } catch {
            spaceError = error.localizedDescription
        }
    }
}
