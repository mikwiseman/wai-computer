import AppKit
import SwiftUI
import WaiComputerKit

enum MacBrainTab: String, CaseIterable {
    case overview
    case index
    case wiki
    case graph
}

/// The macOS "Brain" view: saved sources, approved knowledge, and the context
/// Wai can use. Home is the product surface; Knowledge and Map are secondary
/// inspection views. Honest empty / error+retry states.
struct MacBrainView: View {
    let apiClient: APIClient
    let onOpenSource: (InboxDetailRef) -> Void
    let onOpenInbox: (() -> Void)?
    let onOpenWai: (() -> Void)?

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacBrainViewModel
    @State private var shareEmail = ""
    @State private var shareRole = "viewer"

    init(
        apiClient: APIClient,
        onOpenSource: @escaping (InboxDetailRef) -> Void = { _ in },
        onOpenInbox: (() -> Void)? = nil,
        onOpenWai: (() -> Void)? = nil
    ) {
        self.apiClient = apiClient
        self.onOpenSource = onOpenSource
        self.onOpenInbox = onOpenInbox
        self.onOpenWai = onOpenWai
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
        .onChangeCompat(of: model.selectedSpaceId) { _, _ in
            guard !model.loading else { return }
            Task { await model.loadSelectedSpace() }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(t("Brain", "Мозг")).font(Typography.displaySmall)
            Text(t("Saved sources, approved knowledge, and what Wai can use to help you.",
                   "Сохраненные источники, подтвержденные знания и то, что Wai может использовать."))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.xl)
    }

    private var tabBar: some View {
        HStack(spacing: Spacing.sm) {
            tabButton(.overview, t("Home", "Главная"))
            tabButton(.index, t("Knowledge", "Знания"), isActive: model.tab == .index || model.tab == .wiki)
            tabButton(.graph, t("Map", "Карта"))
            Spacer()
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.sm)
    }

    private func tabButton(_ tab: MacBrainTab, _ label: String, isActive: Bool? = nil) -> some View {
        let active = isActive ?? (model.tab == tab)
        return Button {
            model.tab = tab
        } label: {
            Text(label)
                .font(Typography.label)
                .foregroundStyle(active ? Palette.textPrimary : Palette.textSecondary)
                .padding(.horizontal, Spacing.sm)
                .padding(.vertical, Spacing.xxs)
        }
        .buttonStyle(.plain)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(active ? Palette.accent : Color.clear)
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
            case .overview: overviewView
            case .index: indexView
            case .wiki: wikiView
            case .graph: graphView
            }
        }
    }

    // MARK: - Overview

    @ViewBuilder
    private var overviewView: some View {
        if let graph = model.graph {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.xl) {
                    useWithWaiSection(graph)
                    brainsSection(graph)
                    reviewSuggestionsSection
                    knowledgeSection(graph)
                    sourcesSection(graph)
                    advancedSection
                }
                .padding(Spacing.xl)
                .frame(maxWidth: 900, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
        } else {
            emptyBrain
        }
    }

    @ViewBuilder
    private func useWithWaiSection(_ graph: BrainGraph) -> some View {
        let sourceCount = sourceTotal(graph)
        let approvedCount = approvedKnowledgeCount(model.spaceHome)
        let hasApprovedKnowledge = approvedCount > 0
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(t("Use", "Использовать"))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                    Text(t("Use with Wai", "Использовать с Wai"))
                        .font(Typography.headingSmall)
                    Text(
                        t(
                            "Give Wai a task using approved knowledge from \(selectedBrainName).",
                            "Дайте Wai задачу с подтвержденными знаниями из \(selectedBrainName)."
                        )
                    )
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                }
                Spacer()
                Button {
                    Task { await model.prepareSpaceContext() }
                } label: {
                    Text(model.contextLoading ? t("Preparing", "Готовлю") : t("Use with Wai", "Использовать с Wai"))
                        .frame(minWidth: 120)
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.contextLoading || model.selectedSpaceId.isEmpty || !hasApprovedKnowledge)
            }

            if sourceCount == 0 {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(t(
                        "Add recordings or materials to start building your Brain.",
                        "Добавьте записи или материалы, чтобы начать собирать Мозг."
                    ))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textTertiary)
                    if let onOpenInbox {
                        Button(t("Open Inbox", "Открыть инбокс")) {
                            onOpenInbox()
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }

            if !hasApprovedKnowledge {
                Text(t(
                    "No approved knowledge yet. Approve suggestions first, then Wai can use them.",
                    "Пока нет подтвержденных знаний. Сначала примите предложения, и Wai сможет их использовать."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textTertiary)
            }

            if let message = model.contextMessage {
                Text(message)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
            }

            if let preview = model.contextPreview {
                HStack(spacing: Spacing.xs) {
                    Button(t("Copy context", "Скопировать контекст")) {
                        copyContextToPasteboard()
                    }
                    .buttonStyle(.bordered)
                    Button(t("Open Wai", "Открыть Wai")) {
                        if let onOpenWai {
                            onOpenWai()
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(onOpenWai == nil)
                }
                DisclosureGroup(t("What Wai will see", "Что увидит Wai")) {
                    ScrollView {
                        Text(preview)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(Palette.textSecondary)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.top, Spacing.xs)
                    }
                    .frame(maxHeight: 180)
                }
                .font(Typography.bodySmall)
            }
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder
    private func brainsSection(_ graph: BrainGraph) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                Text(t("Brains", "Мозги")).font(Typography.headingSmall)
                Spacer()
                if !model.spaces.isEmpty {
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
                Text(error)
                    .font(Typography.bodySmall)
                    .foregroundStyle(.red)
            }

            if let home = model.spaceHome {
                HStack(spacing: Spacing.sm) {
                    metricTile(
                        title: t("Sources", "Источники"),
                        value: "\(sourceTotal(graph))",
                        detail: t("recordings and materials", "записи и материалы"),
                        icon: "tray.full"
                    )
                    metricTile(
                        title: t("Knowledge", "Знания"),
                        value: "\(approvedKnowledgeCount(home))",
                        detail: t("approved items", "подтверждено"),
                        icon: "checklist"
                    )
                    metricTile(
                        title: t("Suggestions", "Предложения"),
                        value: "\(suggestionCount)",
                        detail: t("need review", "нужно проверить"),
                        icon: "checkmark.seal"
                    )
                    metricTile(
                        title: t("Notes", "Заметки"),
                        value: "\(home.pageCount)",
                        detail: t("knowledge pages", "страницы знаний"),
                        icon: "doc.text"
                    )
                }
            } else if model.spaces.isEmpty {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    wikiEmpty(t(
                        "Add recordings or materials to start building your Brain.",
                        "Добавьте записи или материалы, чтобы начать собирать Мозг."
                    ))
                    if let onOpenInbox {
                        Button(t("Open Inbox", "Открыть инбокс")) {
                            onOpenInbox()
                        }
                        .buttonStyle(.bordered)
                    }
                }
            } else {
                ProgressView()
            }
        }
    }

    @ViewBuilder
    private var reviewSuggestionsSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                Text(t("Review suggestions", "Проверить предложения")).font(Typography.headingSmall)
                Spacer()
                Text("\(suggestionCount)")
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
            if !model.spaceReviewPacks.isEmpty {
                Text(t(
                    "Wai found possible knowledge for this Brain. Approve only what should guide future answers.",
                    "Wai нашел возможные знания для этого Мозга. Подтверждайте только то, что должно влиять на будущие ответы."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(model.spaceReviewPacks) { pack in
                        spaceReviewPackRow(pack)
                    }
                }
            }
            if !model.proposals.isEmpty {
                Text(t("Memory suggestions", "Предложения памяти"))
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(model.proposals) { proposal in
                        proposalRow(proposal)
                    }
                }
            }
            if suggestionCount == 0 && model.reviewError == nil {
                wikiEmpty(t("No suggestions need review.", "Нет предложений на проверку."))
            }
            if let reviewError = model.reviewError {
                Text(reviewErrorText(reviewError))
                    .font(Typography.bodySmall)
                    .foregroundStyle(.red)
            }
        }
    }

    @ViewBuilder
    private func knowledgeSection(_ graph: BrainGraph) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(t("Knowledge", "Знания")).font(Typography.headingSmall)
            if let home = model.spaceHome, !home.recentPages.isEmpty {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(home.recentPages) { page in
                        brainPageRow(page)
                    }
                }
            }
            let top = graph.overview?.topEntities ?? []
            if !top.isEmpty {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(top) { entity in
                        entityOverviewRow(entity)
                    }
                }
            } else if model.spaceHome?.recentPages.isEmpty != false {
                wikiEmpty(t(
                    "No approved knowledge yet. Review suggestions or add more sources.",
                    "Пока нет подтвержденных знаний. Проверьте предложения или добавьте источники."
                ))
            }
        }
    }

    @ViewBuilder
    private func sourcesSection(_ graph: BrainGraph) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(t("Sources", "Источники")).font(Typography.headingSmall)
            HStack(spacing: Spacing.sm) {
                coverageTile(
                    title: t("Recordings", "Записи"),
                    coverage: graph.overview?.recordings,
                    fallbackTotal: graph.stats["recordings"] ?? 0,
                    icon: "waveform"
                )
                coverageTile(
                    title: t("Materials", "Материалы"),
                    coverage: graph.overview?.materials,
                    fallbackTotal: graph.stats["items"] ?? 0,
                    icon: "doc.text"
                )
            }
            recentSourcesSection(graph)
        }
    }

    @ViewBuilder
    private var advancedSection: some View {
        if let home = model.spaceHome {
            DisclosureGroup(t("Advanced", "Дополнительно")) {
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
                                    if model.shareMessage != nil {
                                        shareEmail = ""
                                    }
                                }
                            } label: {
                                Text(model.sharing ? t("Sharing", "Открываю") : t("Share", "Поделиться"))
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.sharing || shareEmail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                        if let message = model.shareMessage {
                            Text(message)
                                .font(Typography.labelSmall)
                                .foregroundStyle(Palette.textSecondary)
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
                            Text(message)
                                .font(Typography.labelSmall)
                                .foregroundStyle(Palette.textSecondary)
                        }
                    }
                }
                .padding(.top, Spacing.xs)
            }
            .font(Typography.bodySmall)
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
                HStack(spacing: Spacing.xs) {
                    Text(t("Knowledge suggestion", "Предложение знания"))
                        .font(Typography.labelSmall)
                        .padding(.horizontal, Spacing.xs)
                        .padding(.vertical, 2)
                        .background(Palette.accentSubtle)
                        .clipShape(Capsule())
                    Text(pack.risk)
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                }
                Text(pack.title)
                    .font(Typography.bodySmall.weight(.medium))
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
                .help(t("Ignore knowledge suggestion", "Игнорировать предложение знания"))

                Button {
                    Task { await model.acceptSpaceReviewPack(pack.id) }
                } label: {
                    Text(t("Approve", "Подтвердить"))
                }
                .buttonStyle(.borderedProminent)
                .disabled(acting)
                .help(t("Approve knowledge suggestion", "Подтвердить предложение знания"))
            }
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var selectedBrainName: String {
        model.spaces.first { $0.id == model.selectedSpaceId }?.name ?? t("Personal", "Личный")
    }

    private var suggestionCount: Int {
        model.spaceReviewPacks.count + max(model.pendingReviewCount, model.proposals.count)
    }

    private func sourceTotal(_ graph: BrainGraph) -> Int {
        if let home = model.spaceHome {
            return home.sourceCount
        }
        return (graph.overview?.recordings.total ?? graph.stats["recordings"] ?? 0)
            + (graph.overview?.materials.total ?? graph.stats["items"] ?? 0)
    }

    private func approvedKnowledgeCount(_ home: BrainSpaceHome?) -> Int {
        home?.claimCounts.values.reduce(0, +) ?? 0
    }

    private func copyContextToPasteboard() {
        guard let preview = model.contextPreview else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(preview, forType: .string)
        model.contextMessage = t("Context copied.", "Контекст скопирован.")
    }

    private func brainPageRow(_ page: BrainPage) -> some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "doc.text")
                .font(.system(size: 11))
                .foregroundStyle(Palette.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text(page.title).font(Typography.bodySmall.weight(.medium))
                Text(
                    t(
                        "\(page.kind) · \(page.claims.count) approved items",
                        "\(page.kind) · \(page.claims.count) подтверждено"
                    )
                )
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textSecondary)
            }
            Spacer()
        }
        .padding(Spacing.sm)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func entityOverviewRow(_ entity: BrainOverviewEntity) -> some View {
        Button {
            model.openEntity(id: entity.id, name: entity.name)
        } label: {
            HStack(spacing: Spacing.sm) {
                Image(systemName: entityIcon(entity.type))
                    .font(.system(size: 11))
                    .foregroundStyle(Palette.accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(entity.name).font(Typography.bodySmall.weight(.medium))
                    Text(
                        t(
                            "\(entity.recordingCount) recordings · \(entity.materialCount) materials",
                            "\(entity.recordingCount) записей · \(entity.materialCount) материалов"
                        )
                    )
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
                }
                Spacer()
                Text("\(entity.sourceCount)")
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
            .padding(Spacing.sm)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }

    private func exportProfileLabel(_ profile: String) -> String {
        switch profile {
        case "obsidian":
            return t("Export to Obsidian", "Экспорт в Obsidian")
        case "mempalace":
            return t("Export to MemPalace", "Экспорт в MemPalace")
        case "gbrain":
            return t("Export to G Brain", "Экспорт в G Brain")
        default:
            return t("Export notes", "Экспортировать заметки")
        }
    }

    private func sourceCountsLabel(_ home: BrainSpaceHome) -> String {
        let parts = home.sourceCounts.sorted(by: { $0.key < $1.key }).map { "\($0.key) \($0.value)" }
        return parts.isEmpty ? t("none", "нет") : parts.joined(separator: " · ")
    }

    private func claimCountsLabel(_ home: BrainSpaceHome) -> String {
        let parts = home.claimCounts.sorted(by: { $0.key < $1.key }).map { "\($0.key) \($0.value)" }
        return parts.isEmpty ? t("none", "нет") : parts.joined(separator: " · ")
    }

    private func coverageTile(
        title: String,
        coverage: BrainSourceCoverage?,
        fallbackTotal: Int,
        icon: String
    ) -> some View {
        let total = coverage?.total ?? fallbackTotal
        let organized = coverage?.organized ?? fallbackTotal
        let unorganized = coverage?.unorganized ?? max(total - organized, 0)
        let summarized = coverage?.summarized ?? organized
        return VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: icon)
                    .font(.system(size: 12))
                    .foregroundStyle(Palette.accent)
                Text(title).font(Typography.label)
            }
            Text("\(organized) / \(total)")
                .font(Typography.headingSmall)
            Text(
                t(
                    "\(summarized) summarized · \(unorganized) not organized",
                    "\(summarized) с саммари · \(unorganized) не организовано"
                )
            )
            .font(Typography.labelSmall)
            .foregroundStyle(Palette.textSecondary)
            .lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func metricTile(title: String, value: String, detail: String, icon: String) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: icon)
                    .font(.system(size: 12))
                    .foregroundStyle(Palette.accent)
                Text(title).font(Typography.label)
            }
            Text(value).font(Typography.headingSmall)
            Text(detail)
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func proposalRow(_ proposal: MemoryProposal) -> some View {
        let acting = model.actingProposalIds.contains(proposal.id)
        return HStack(alignment: .top, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                HStack(spacing: Spacing.xs) {
                    Text(proposal.isHighRisk ? t("Correction", "Исправление") : t("New fact", "Новый факт"))
                        .font(Typography.labelSmall)
                        .padding(.horizontal, Spacing.xs)
                        .padding(.vertical, 2)
                        .background(Palette.accentSubtle)
                        .clipShape(Capsule())
                    Text(sectionTitle(proposal.blockLabel))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                    Text("\(Int((proposal.confidence * 100).rounded()))%")
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                }
                Text(proposal.content)
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if proposal.operation == "replace_line", let target = proposal.targetLine,
                   !target.isEmpty {
                    Text(t("Replaces: ", "Заменяет: ") + target)
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                }
                if let evidence = evidenceLabel(proposal), !evidence.isEmpty {
                    Text(evidence)
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: Spacing.sm)
            HStack(spacing: Spacing.sm) {
                Button {
                    Task { await model.rejectProposal(proposal.id) }
                } label: {
                    Text(t("Ignore", "Игнорировать"))
                }
                .buttonStyle(.bordered)
                .help(t("Ignore memory suggestion", "Игнорировать предложение памяти"))
                .disabled(acting)

                Button {
                    Task { await model.acceptProposal(proposal.id) }
                } label: {
                    Text(t("Approve", "Подтвердить"))
                }
                .buttonStyle(.borderedProminent)
                .help(t("Approve memory suggestion", "Подтвердить предложение памяти"))
                .disabled(acting)
            }
            .opacity(acting ? 0.5 : 1)
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder
    private func recentSourcesSection(_ graph: BrainGraph) -> some View {
        let sources = graph.overview?.recentSources ?? []
        if !sources.isEmpty {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                Text(t("Recent sources", "Недавние источники"))
                    .font(Typography.headingSmall)
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    ForEach(sources) { source in
                        Button {
                            openSource(kind: source.sourceKind, id: source.sourceId)
                        } label: {
                            HStack(spacing: Spacing.sm) {
                                Image(systemName: source.sourceKind == "recording" ? "waveform" : "doc.text")
                                    .font(.system(size: 11))
                                    .foregroundStyle(Palette.accent)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(source.title)
                                        .font(Typography.bodySmall.weight(.medium))
                                        .lineLimit(1)
                                    Text(
                                        t(
                                            "\(source.entityCount) entities · \(sourceKindLabel(source.sourceKind))",
                                            "\(source.entityCount) сущностей · \(sourceKindLabel(source.sourceKind))"
                                        )
                                    )
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
                }
            }
        }
    }

    // MARK: - Graph

    @ViewBuilder
    private var graphView: some View {
        if let graph = model.graph, !graph.nodes.isEmpty {
            MacBrainGraphView(
                graph: graph,
                onOpenEntity: { node in
                    if node.kind == "person" || node.kind == "topic" || node.kind == "project" {
                        model.openEntity(id: node.id, name: node.label)
                    }
                },
                onOpenSource: { detail in
                    onOpenSource(detail)
                }
            )
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
                description: Text(t("Choose one from Knowledge to read its page.",
                                    "Выберите элемент в Знаниях, чтобы открыть страницу."))
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
            } else if !page.related.isEmpty {
                VStack(alignment: .leading, spacing: Spacing.xs) {
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

    private func openSource(kind: String, id: String) {
        guard let sourceKind = InboxSourceKind(rawValue: kind) else { return }
        guard sourceKind == .recording || sourceKind == .item else { return }
        onOpenSource(InboxDetailRef(kind: sourceKind, id: id))
    }

    private func evidenceLabel(_ proposal: MemoryProposal) -> String? {
        guard let evidence = proposal.evidence else { return nil }
        for value in evidence {
            guard let object = value.objectValue else { continue }
            if let title = object["title"]?.stringValue, !title.isEmpty {
                return t("Evidence: ", "Источник: ") + title
            }
            if let sourceKind = object["source_kind"]?.stringValue,
               let sourceId = object["source_id"]?.stringValue,
               !sourceKind.isEmpty, !sourceId.isEmpty {
                return t("Evidence: ", "Источник: ") + "\(sourceKind):\(sourceId)"
            }
        }
        return nil
    }

    private func reviewErrorText(_ error: MacBrainViewModel.ReviewError) -> String {
        switch error {
        case .load:
            return t("Couldn't load memory changes for review.",
                     "Не удалось загрузить изменения памяти на проверку.")
        case .action:
            return t("That review action didn't go through.",
                     "Действие проверки не выполнилось.")
        }
    }

    private func sectionTitle(_ label: String) -> String {
        switch label {
        case "human": return t("About you", "О вас")
        case "topics": return t("Recurring topics", "Повторяющиеся темы")
        case "preferences": return t("Preferences", "Предпочтения")
        default: return label.capitalized
        }
    }

    private func sourceKindLabel(_ kind: String) -> String {
        switch kind {
        case "recording": return t("recording", "запись")
        case "item": return t("material", "материал")
        default: return kind
        }
    }

    // MARK: - Shared

    private var emptyBrain: some View {
        ContentUnavailableViewCompat(
            t("Your brain is empty", "Ваш мозг пуст"),
            systemImage: "brain",
            description: Text(t(
                "Add recordings or materials to start building your Brain.",
                "Добавьте записи или материалы, чтобы начать собирать Мозг."
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
    @Published var tab: MacBrainTab = .overview
    @Published var selectedEntity: SelectedEntity?
    @Published var entityPage: EntityPage?
    @Published var pageLoading = false
    @Published var pageError: String?
    @Published var proposals: [MemoryProposal] = []
    @Published var pendingReviewCount = 0
    @Published var actingProposalIds: Set<String> = []
    @Published var reviewError: ReviewError?
    @Published var spaces: [BrainSpace] = []
    @Published var selectedSpaceId = ""
    @Published var spaceHome: BrainSpaceHome?
    @Published var spaceReviewPacks: [BrainReviewPack] = []
    @Published var spaceError: String?
    @Published var contextLoading = false
    @Published var contextMessage: String?
    @Published var contextPreview: String?
    @Published var sharing = false
    @Published var shareMessage: String?
    @Published var exportMessage: String?
    @Published var actingSpaceReviewPackIds: Set<String> = []

    private let apiClient: APIClient

    enum ReviewError {
        case load
        case action
    }

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
            return
        }
        await loadSpaces()
        await loadSelectedSpace()
        do {
            let review = try await apiClient.listMemoryProposals(status: "pending")
            proposals = review.proposals
            pendingReviewCount = review.pendingCount
            reviewError = nil
        } catch {
            reviewError = .load
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

    func prepareSpaceContext() async {
        guard !selectedSpaceId.isEmpty, !contextLoading else { return }
        contextLoading = true
        contextMessage = nil
        defer { contextLoading = false }
        do {
            let context = try await apiClient.buildBrainContext(
                spaceId: selectedSpaceId,
                task: "Use this Brain as the source of truth.",
                limit: 80
            )
            contextPreview = context.markdown
            if context.claimCount == 0 {
                contextMessage = "No approved knowledge yet. Approve suggestions first, then Wai can use them."
            } else {
                contextMessage = "\(context.claimCount) approved items ready for Wai."
            }
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

    func acceptProposal(_ id: String) async {
        await decideProposal(id) { try await self.apiClient.acceptMemoryProposal(id: id) }
    }

    func rejectProposal(_ id: String) async {
        await decideProposal(id) { try await self.apiClient.rejectMemoryProposal(id: id) }
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

    private func decideProposal(
        _ id: String,
        action: @escaping () async throws -> MemoryProposal
    ) async {
        guard !actingProposalIds.contains(id) else { return }
        actingProposalIds.insert(id)
        defer { actingProposalIds.remove(id) }
        do {
            _ = try await action()
            proposals.removeAll { $0.id == id }
            pendingReviewCount = max(0, pendingReviewCount - 1)
            reviewError = nil
        } catch {
            reviewError = .action
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
