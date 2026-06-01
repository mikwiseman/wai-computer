import SwiftUI
import WaiComputerKit

/// The "Brain" tab: the second-brain home. A universal feed of captured items
/// (links, notes, files, MCP-ingested rows) with add-anything capture. Entries
/// to the compiled-wiki Brain, the Review queue, and Comparisons are layered in
/// alongside this feed.
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
            Group {
                if model.entries.isEmpty && !model.isLoading {
                    emptyState
                } else {
                    feedList
                }
            }
            .navigationTitle(t("Brain", "Мозг"))
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showAdd = true
                    } label: {
                        Image(systemName: "plus")
                    }
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

    private var emptyState: some View {
        ContentUnavailableViewCompat(
            t("Your brain is empty", "Ваш мозг пуст"),
            systemImage: "brain",
            description: Text(t(
                "Tap + to save a link or a note. WaiComputer summarizes it and makes it searchable forever.",
                "Нажмите +, чтобы сохранить ссылку или заметку. WaiComputer сделает конспект и навсегда добавит в поиск."
            ))
        )
    }

    private var feedList: some View {
        List {
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
        .listStyle(.plain)
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
