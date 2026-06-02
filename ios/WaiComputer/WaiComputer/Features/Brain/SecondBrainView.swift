import SwiftUI
import WaiComputerKit

/// The "Brain" tab: the second-brain home. A universal feed of captured items
/// (links, notes, files, MCP-ingested rows) with add-anything capture, plus
/// entries to the compiled-wiki Memory, the Review queue, and Comparisons.
struct SecondBrainView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: ContentFeedViewModel
    @State private var showAdd = false

    init(apiClient: APIClient) {
        _model = StateObject(wrappedValue: ContentFeedViewModel(apiClient: apiClient))
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        NavigationStack {
            List {
                if model.isSearchActive {
                    searchSection
                } else {
                Section {
                    NavigationLink {
                        MemoryView(apiClient: model.apiClient)
                    } label: {
                        entryRow(icon: "brain", title: t("Memory", "Память"), badge: nil)
                    }
                    NavigationLink {
                        ReviewView(apiClient: model.apiClient)
                    } label: {
                        entryRow(icon: "tray.full", title: t("Review", "На проверку"),
                                 badge: model.pendingReviewCount)
                    }
                    NavigationLink {
                        ComparisonListView(apiClient: model.apiClient)
                    } label: {
                        entryRow(icon: "tablecells", title: t("Compare", "Сравнить"), badge: nil)
                    }
                }

                Section(header: Text(t("Captured", "Сохранённое"))) {
                    if model.entries.isEmpty {
                        Text(t("Tap + to save a link or a note — summarized and searchable forever.",
                               "Нажмите +, чтобы сохранить ссылку или заметку — с конспектом и навсегда в поиске."))
                            .font(Typography.bodySmall)
                            .foregroundStyle(Palette.textSecondary)
                    } else {
                        ForEach(model.entries) { entry in
                            NavigationLink {
                                ItemDetailView(itemId: entry.id, apiClient: model.apiClient) {
                                    Task { await model.load() }
                                }
                            } label: {
                                row(entry)
                            }
                        }
                        .onDelete { offsets in
                            let ids = offsets.map { model.entries[$0].id }
                            Task { for id in ids { await model.delete(id) } }
                        }
                    }
                }
                }
            }
            .listStyle(.insetGrouped)
            .searchable(text: $model.query, prompt: t("Search everything", "Искать везде"))
            .task(id: model.query) {
                try? await Task.sleep(nanoseconds: 300_000_000)
                if !Task.isCancelled { await model.search() }
            }
            .navigationTitle(t("Brain", "Мозг"))
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showAdd = true } label: { Image(systemName: "plus") }
                        .accessibilityIdentifier("brain-add-button")
                }
            }
            .sheet(isPresented: $showAdd) {
                AddAnythingSheet(isPresented: $showAdd, isAdding: model.isAdding) { text in
                    Task {
                        if await model.add(text) != nil { showAdd = false }
                    }
                }
            }
            .refreshable { await model.load() }
            .task { await model.load() }
            .overlay(alignment: .bottom) {
                if let error = model.errorMessage {
                    Text(error)
                        .font(Typography.bodySmall)
                        .foregroundStyle(.white)
                        .padding(Spacing.sm)
                        .background(.red, in: Capsule())
                        .padding(.bottom, Spacing.md)
                }
            }
        }
    }

    @ViewBuilder
    private var searchSection: some View {
        if model.isSearching && model.searchResults.isEmpty {
            Section { ProgressView() }
        } else if model.searchResults.isEmpty {
            Section {
                Text(t("No results", "Ничего не найдено"))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
            }
        } else {
            Section(header: Text(t("Results", "Результаты"))) {
                ForEach(model.searchResults, id: \.chunkId) { hit in
                    NavigationLink {
                        destination(for: hit)
                    } label: {
                        hitRow(hit)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func destination(for hit: UnifiedHit) -> some View {
        if hit.sourceKind == "item" {
            ItemDetailView(itemId: hit.parentId, apiClient: model.apiClient) {
                Task { await model.load() }
            }
        } else {
            RecordingDetailView(recording: Recording(id: hit.parentId, type: .meeting, createdAt: Date()))
        }
    }

    private func hitRow(_ hit: UnifiedHit) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(hit.title ?? t("Untitled", "Без названия"))
                .font(Typography.body.weight(.medium))
                .lineLimit(1)
            Text(hit.snippet)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2)
            Text(hit.sourceKind == "item" ? hit.kind.uppercased() : t("RECORDING", "ЗАПИСЬ"))
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
        }
        .padding(.vertical, Spacing.xxs)
    }

    private func entryRow(icon: String, title: String, badge: Int?) -> some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: icon)
                .font(.system(size: 15))
                .foregroundStyle(Palette.accent)
                .frame(width: 24)
            Text(title).font(Typography.body)
            Spacer()
            if let badge, badge > 0 {
                Text("\(badge)")
                    .font(Typography.labelSmall.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 2)
                    .background(Palette.accent, in: Capsule())
            }
        }
    }

    private func row(_ entry: ItemListEntry) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(entry.title ?? t("Untitled", "Без названия"))
                .font(Typography.body.weight(.medium))
                .lineLimit(2)
            HStack(spacing: Spacing.xs) {
                Text(entry.kind.uppercased())
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.accent)
                if !entry.hasSummary {
                    Text(t("· summarizing…", "· конспект…"))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                }
            }
        }
        .padding(.vertical, Spacing.xxs)
    }
}
