import SwiftUI
import WaiComputerKit

/// A generated Brain map surface — live-status (changed/updated/stale + metrics),
/// a briefing (focus note, coverage, suggested questions, top sources/entities),
/// the map's node graph, an evidence list, and Refresh/Keep actions. Bound to a
/// single `BrainMap`; manages its own refresh/keep against the shared API.
/// Ported from the macOS Brain `generatedMapSurface`/`generatedBriefing`.
struct BrainMapDetailView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var map: BrainMap
    @State private var refreshing = false
    @State private var keeping = false
    @State private var error: String?
    @State private var autoRefreshed = false

    let apiClient: APIClient

    init(map: BrainMap, apiClient: APIClient) {
        _map = State(initialValue: map)
        self.apiClient = apiClient
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    private var projection: BrainMapProjection? { map.currentRevision?.projection }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                headerSection
                if let revision = map.currentRevision {
                    liveStatus(revision)
                }
                if let projection {
                    if let briefing = projection.briefing {
                        briefingSection(briefing)
                    }
                    BrainMapCanvasView(projection: projection, apiClient: apiClient, compact: false)
                        .frame(height: 280)
                    statsSection(projection)
                    if !projection.citations.isEmpty {
                        evidenceSection(projection.citations)
                    }
                } else {
                    Text(t("This map has not been compiled yet.", "Эта карта ещё не собрана."))
                        .font(Typography.bodySmall).foregroundStyle(Palette.textSecondary)
                }
                if let error {
                    Text(error).font(Typography.labelSmall).foregroundStyle(.red)
                }
            }
            .padding(Spacing.lg)
        }
        .navigationTitle(map.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                if map.status == "draft" {
                    Button(keeping ? t("Keeping…", "Сохраняю…") : t("Keep", "Сохранить")) {
                        Task { await keep() }
                    }
                    .disabled(keeping)
                }
                Button {
                    Task { await refresh() }
                } label: {
                    if refreshing {
                        ProgressView()
                    } else {
                        Image(systemName: "arrow.clockwise")
                    }
                }
                .disabled(refreshing)
            }
        }
        .task {
            guard !autoRefreshed else { return }
            autoRefreshed = true
            await refresh()
        }
    }

    private var headerSection: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(map.title).font(Typography.headingLarge)
            if let summary = projection?.summary, !summary.isEmpty {
                Text(summary).font(Typography.bodySmall).foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(mapOriginLabel(map.origin)).font(Typography.labelSmall).foregroundStyle(Palette.textTertiary)
        }
    }

    private func liveStatus(_ revision: BrainMapRevision) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.xs) {
                Circle()
                    .fill(revision.freshness.stale ? Color.orange : (revision.diff.changed ? Palette.accent : Color.green))
                    .frame(width: 8, height: 8)
                Text(statusHeadline(revision)).font(Typography.bodySmall.weight(.semibold)).foregroundStyle(Palette.textPrimary)
                Spacer()
                Text(t("rev \(revision.revisionIndex)", "ред. \(revision.revisionIndex)"))
                    .font(Typography.labelSmall).foregroundStyle(Palette.textTertiary)
            }
            Text(mapChangeDetail(revision.diff)).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
            Text(mapFreshnessLabel(revision.freshness)).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
            Text(mapWatchText(revision, projection: revision.projection))
                .font(Typography.labelSmall).foregroundStyle(Palette.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(Spacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func briefingSection(_ briefing: BrainMapBriefing) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(briefing.headline).font(Typography.headingSmall).foregroundStyle(Palette.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            if !briefing.focusNote.isEmpty {
                Text(briefing.focusNote).font(Typography.bodySmall).foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: Spacing.sm) {
                coverageTile("\(briefing.coverage.visibleSources)/\(briefing.coverage.totalSources)", t("sources", "источн."))
                coverageTile("\(briefing.coverage.visibleEntities)/\(briefing.coverage.totalEntities)", t("entities", "узлов"))
            }
            if !briefing.freshnessNote.isEmpty {
                Text(briefing.freshnessNote).font(Typography.labelSmall).foregroundStyle(Palette.textTertiary)
            }
            if !briefing.suggestedQuestions.isEmpty {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(t("Suggested questions", "Подсказки")).font(Typography.labelSmall.weight(.semibold))
                        .foregroundStyle(Palette.textSecondary)
                    ForEach(briefing.suggestedQuestions.prefix(3), id: \.self) { question in
                        Text("• " + question).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .padding(Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.035))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Palette.border, lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func coverageTile(_ value: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value).font(Typography.headingSmall).foregroundStyle(Palette.textPrimary)
            Text(label).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
        }
        .padding(Spacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func statsSection(_ projection: BrainMapProjection) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Spacing.sm) {
                metricPill("\(projection.nodes.count)", t("cards", "карточек"))
                metricPill("\(projection.edges.count)", t("links", "связей"))
                metricPill("\(projection.citations.count)", t("sources", "источн."))
            }
        }
    }

    private func evidenceSection(_ citations: [BrainMapCitation]) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(t("Evidence", "Источники")).waiSectionHeader()
            ForEach(citations) { citation in
                evidenceRow(citation)
            }
        }
    }

    @ViewBuilder
    private func evidenceRow(_ citation: BrainMapCitation) -> some View {
        let row = HStack(spacing: Spacing.sm) {
            Image(systemName: sourceKindSystemImage(citation.sourceKind)).font(.system(size: 11)).foregroundStyle(Palette.accent).frame(width: 16)
            Text(citation.title).font(Typography.bodySmall).foregroundStyle(Palette.textPrimary).lineLimit(2)
            Spacer(minLength: 0)
            if let date = citation.createdAt { Text(String(date.prefix(10))).font(Typography.labelSmall).foregroundStyle(Palette.textTertiary) }
        }
        .padding(Spacing.sm)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))

        switch citation.sourceKind {
        case "recording":
            NavigationLink { RecordingDetailView(recording: Recording(id: citation.sourceId, type: .meeting, createdAt: Date())) } label: { row }.buttonStyle(.plain)
        case "item":
            NavigationLink { ItemDetailView(itemId: citation.sourceId, apiClient: apiClient) {} } label: { row }.buttonStyle(.plain)
        default:
            row
        }
    }

    // MARK: - Actions

    private func refresh() async {
        guard !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            _ = try await apiClient.refreshBrainMap(mapId: map.id)
            map = try await apiClient.getBrainMap(mapId: map.id)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func keep() async {
        guard !keeping else { return }
        keeping = true
        defer { keeping = false }
        do {
            map = try await apiClient.updateBrainMap(mapId: map.id, BrainMapUpdateRequest(status: "saved"))
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    // MARK: - Helpers (ported from MacBrainView)

    private func statusHeadline(_ revision: BrainMapRevision) -> String {
        if revision.freshness.stale { return t("Stale — new sources arrived", "Устарело — появились новые источники") }
        if revision.diff.changed { return t("Updated from sources", "Обновлено из источников") }
        return t("Current", "Актуально")
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

    private func mapChangeDetail(_ diff: BrainMapDiff) -> String {
        let parts = [
            signedChange(added: diff.sourcesAdded, removed: diff.sourcesRemoved, label: "sources", labelRu: "источн."),
            signedChange(added: diff.nodesAdded, removed: diff.nodesRemoved, label: "cards", labelRu: "карточек"),
            signedChange(added: diff.edgesAdded, removed: diff.edgesRemoved, label: "links", labelRu: "связей")
        ].compactMap { $0 }
        if !parts.isEmpty { return parts.joined(separator: " · ") }
        return t("No source changes", "Источники не изменились")
    }

    private func signedChange(added: Int, removed: Int, label: String, labelRu: String) -> String? {
        if added == 0 && removed == 0 { return nil }
        let textLabel = t(label, labelRu)
        if removed == 0 { return "+\(added) \(textLabel)" }
        if added == 0 { return "-\(removed) \(textLabel)" }
        return "+\(added) / -\(removed) \(textLabel)"
    }

    private func mapFreshnessLabel(_ freshness: BrainMapFreshness) -> String {
        if let weeks = freshness.weeksSince {
            if weeks == 0 { return t("Newest source this week", "Новый источник на этой неделе") }
            return t("Newest source \(weeks) weeks old", "Новейшему источнику \(weeks) нед.")
        }
        if freshness.newestSourceAt == nil { return t("No dated source", "Нет источника с датой") }
        return t("Current source set", "Актуальный набор источников")
    }

    private func mapWatchText(_ revision: BrainMapRevision, projection: BrainMapProjection) -> String {
        if revision.freshness.stale {
            return t("Ask what changed before relying on it.", "Спроси, что изменилось, прежде чем полагаться.")
        }
        if revision.diff.changed {
            return t("Review new evidence, then keep the map if it still matches reality.",
                     "Проверь новые источники и сохрани карту, если она всё ещё верна.")
        }
        return t("Safe to use for the current source set.", "Можно использовать для текущего набора источников.")
    }

    private func mapOriginLabel(_ origin: String) -> String {
        switch origin {
        case "inbox": return t("Inbox source", "Источник из инбокса")
        case "agent": return t("Agent", "Агент")
        case "wai": return "Wai"
        default: return t("Brain lens", "Линза мозга")
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
