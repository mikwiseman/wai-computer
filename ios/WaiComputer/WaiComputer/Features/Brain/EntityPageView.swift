import SwiftUI
import WaiComputerKit

/// A living entity dossier — the rich `EntityPage` (Overview, Facts, Timeline,
/// Related-with-explanations, Open questions, Actions, Sources, Citations), each
/// section evidence-linked back to its sources. Ported from the macOS Brain
/// `dossierView`/`wikiBody`; a pushed iOS screen instead of an in-place swap.
struct EntityPageView: View {
    let entityId: String
    let name: String
    let apiClient: APIClient

    @EnvironmentObject private var languageManager: LanguageManager
    @State private var page: EntityPage?
    @State private var loading = true
    @State private var error: String?

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        Group {
            if let page {
                dossier(page)
            } else if loading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: Spacing.md) {
                    ContentUnavailableViewCompat(
                        t("Couldn't load this page", "Не удалось загрузить страницу"),
                        systemImage: "exclamationmark.triangle",
                        description: error.map { Text($0) }
                    )
                    Button(t("Retry", "Повторить")) { Task { await load() } }
                        .buttonStyle(.borderedProminent)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle(name)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func load() async {
        loading = true
        error = nil
        defer { loading = false }
        do {
            page = try await apiClient.getEntityPage(id: entityId)
        } catch {
            self.error = error.localizedDescription
        }
    }

    // MARK: - Dossier

    private func dossier(_ page: EntityPage) -> some View {
        let citationIndex = Dictionary(uniqueKeysWithValues: page.citations.enumerated().map { ($0.element.id, $0.offset + 1) })
        return ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                header(page)

                if !page.overview.isEmpty {
                    section(t("Overview", "Обзор")) {
                        Text(page.overview)
                            .font(Typography.reading)
                            .foregroundStyle(Palette.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                    }
                }

                if !page.facts.isEmpty {
                    section(t("Facts", "Факты")) {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            ForEach(page.facts) { fact in
                                bulletRow(fact.text, refs: fact.citationIds, index: citationIndex)
                            }
                        }
                    }
                }

                if !page.timeline.isEmpty {
                    section(t("Timeline", "Хронология")) {
                        VStack(alignment: .leading, spacing: Spacing.md) {
                            ForEach(page.timeline) { event in
                                timelineRow(event, index: citationIndex)
                            }
                        }
                    }
                }

                if !page.relatedExplanations.isEmpty {
                    section(t("Related", "Связанное")) {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            ForEach(page.relatedExplanations) { related in
                                relatedRow(related, index: citationIndex)
                            }
                        }
                    }
                } else if !page.related.isEmpty {
                    section(t("Related", "Связанное")) {
                        FlowChips(items: page.related.map { "\($0.name) · \($0.shared)" })
                    }
                }

                if !page.questions.isEmpty {
                    section(t("Open questions", "Открытые вопросы")) {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            ForEach(page.questions) { question in
                                bulletRow(question.text, refs: question.citationIds, index: citationIndex, symbol: "questionmark.circle")
                            }
                        }
                    }
                }

                if !page.actions.isEmpty {
                    section(t("Actions", "Действия")) {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            ForEach(page.actions) { action in
                                actionRow(action, index: citationIndex)
                            }
                        }
                    }
                }

                if !page.citations.isEmpty {
                    section(t("Sources", "Источники")) {
                        VStack(alignment: .leading, spacing: Spacing.xs) {
                            ForEach(Array(page.citations.enumerated()), id: \.element.id) { offset, citation in
                                citationRow(citation, number: offset + 1)
                            }
                        }
                    }
                }
            }
            .padding(Spacing.lg)
        }
    }

    private func header(_ page: EntityPage) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: entityIcon(page.type))
                    .font(.system(size: 20))
                    .foregroundStyle(Palette.accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(page.name).font(Typography.displaySmall)
                    Text(entityTypeLabel(page.type) + " · " + t("\(page.mentionCount) mentions", "\(page.mentionCount) упоминаний"))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                }
            }
            if page.cacheStatus == "stale" {
                Text(t("Refreshing in the background…", "Обновляется в фоне…"))
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(title).waiSectionHeader()
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func bulletRow(_ text: String, refs: [String], index: [String: Int], symbol: String = "circle.fill") -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: symbol)
                .font(.system(size: symbol == "circle.fill" ? 5 : 12))
                .foregroundStyle(Palette.accent)
                .padding(.top, symbol == "circle.fill" ? 7 : 1)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(text).font(Typography.bodySmall).foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                citationRefs(refs, index: index)
            }
        }
    }

    private func timelineRow(_ event: EntityPageTimelineEvent, index: [String: Int]) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            VStack(spacing: 0) {
                Circle().fill(Palette.accent).frame(width: 8, height: 8)
                Rectangle().fill(Palette.border).frame(width: 1.5).frame(maxHeight: .infinity)
            }
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                if let date = event.occurredAt, !date.isEmpty {
                    Text(String(date.prefix(10))).font(Typography.labelSmall.weight(.semibold))
                        .foregroundStyle(Palette.textSecondary)
                }
                Text(event.title).font(Typography.bodySmall.weight(.medium)).foregroundStyle(Palette.textPrimary)
                if let description = event.description, !description.isEmpty {
                    Text(description).font(Typography.bodySmall).foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                citationRefs(event.citationIds, index: index)
            }
            Spacer(minLength: 0)
        }
    }

    private func relatedRow(_ related: EntityPageRelatedExplanation, index: [String: Int]) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: entityIcon(related.type)).font(.system(size: 11)).foregroundStyle(Palette.accent)
                Text(related.name).font(Typography.bodySmall.weight(.semibold)).foregroundStyle(Palette.textPrimary)
                Text(t("\(related.shared) shared", "\(related.shared) общих"))
                    .font(Typography.labelSmall).foregroundStyle(Palette.textTertiary)
            }
            Text(related.explanation).font(Typography.bodySmall).foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            citationRefs(related.citationIds, index: index)
        }
        .padding(Spacing.sm)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func actionRow(_ action: EntityPageAction, index: [String: Int]) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: "checkmark.square").font(.system(size: 13)).foregroundStyle(Palette.accent).padding(.top, 1)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(action.text).font(Typography.bodySmall).foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                let meta = [action.owner, action.dueDate.map { String($0.prefix(10)) }, action.status].compactMap { $0 }.filter { !$0.isEmpty }
                if !meta.isEmpty {
                    Text(meta.joined(separator: " · ")).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
                }
                citationRefs(action.citationIds, index: index)
            }
        }
    }

    @ViewBuilder
    private func citationRefs(_ refs: [String], index: [String: Int]) -> some View {
        let numbers = refs.compactMap { index[$0] }.sorted()
        if !numbers.isEmpty {
            HStack(spacing: 4) {
                ForEach(numbers, id: \.self) { number in
                    Text("[\(number)]")
                        .font(Typography.labelSmall.weight(.semibold))
                        .foregroundStyle(Palette.accent)
                }
            }
        }
    }

    private func citationRow(_ citation: EntityPageCitation, number: Int) -> some View {
        let row = HStack(alignment: .top, spacing: Spacing.sm) {
            Text("\(number)").font(Typography.labelSmall.weight(.semibold)).foregroundStyle(Palette.accent)
                .frame(width: 20, alignment: .trailing)
            VStack(alignment: .leading, spacing: 1) {
                Text(citation.title).font(Typography.bodySmall.weight(.medium)).foregroundStyle(Palette.textPrimary).lineLimit(2)
                if let context = citation.context, !context.isEmpty {
                    Text(context).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary).lineLimit(2)
                }
            }
            Spacer(minLength: 0)
            Image(systemName: sourceKindSystemImage(citation.sourceKind)).font(.system(size: 11)).foregroundStyle(Palette.textTertiary)
        }
        .padding(Spacing.sm)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))

        return Group {
            switch citation.sourceKind {
            case "recording":
                NavigationLink { RecordingDetailView(recording: Recording(id: citation.sourceId, type: .meeting, createdAt: Date())) } label: { row }
                    .buttonStyle(.plain)
            case "item":
                NavigationLink { ItemDetailView(itemId: citation.sourceId, apiClient: apiClient) {} } label: { row }
                    .buttonStyle(.plain)
            default:
                row
            }
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

    private func entityTypeLabel(_ type: String) -> String {
        switch type {
        case "person": return t("Person", "Человек")
        case "project": return t("Project", "Проект")
        case "organization": return t("Organization", "Организация")
        case "topic": return t("Topic", "Тема")
        default: return type.capitalized
        }
    }

    private func sourceKindSystemImage(_ kind: String) -> String {
        switch kind {
        case "recording": return "waveform"
        case "chat": return "bubble.left.and.bubble.right"
        default: return "doc.text"
        }
    }
}

/// A simple wrapping chip row for short related-entity labels.
private struct FlowChips: View {
    let items: [String]

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Spacing.xs) {
                ForEach(items, id: \.self) { item in
                    Text(item)
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textSecondary)
                        .padding(.horizontal, Spacing.sm)
                        .padding(.vertical, Spacing.xxs)
                        .background(Palette.surfaceSubtle)
                        .clipShape(Capsule())
                }
            }
        }
    }
}
