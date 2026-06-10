import SwiftUI
import WaiComputerKit

/// The iOS "Materials" tab — the captured-items inbox (links, notes, files),
/// summarized and searchable. Capture and recall stay front and center; the
/// knowledge mechanics (entity graph, recall ranking) run in the background
/// and surface through unified search and the MCP server.
struct MaterialsView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var feed: ContentFeedViewModel

    let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
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
                    CapturedFeedView(model: feed)
                }
            }
            .navigationTitle(t("Materials", "Материалы"))
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $feed.query, prompt: t("Search everything", "Искать везде"))
            .task(id: feed.query) {
                try? await Task.sleep(nanoseconds: 300_000_000)
                if !Task.isCancelled { await feed.search() }
            }
        }
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
}
