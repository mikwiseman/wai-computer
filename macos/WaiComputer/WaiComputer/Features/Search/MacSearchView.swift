import SwiftUI
import WaiComputerKit

struct MacSearchView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var viewModel = MacSearchViewModel()

    var body: some View {
        VStack(spacing: 0) {
            searchHeader

            WaiDivider()

            searchResults
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .onChange(of: viewModel.searchMode) { _, _ in
            performSearch()
        }
    }

    private var searchHeader: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(Palette.textTertiary)

                TextField(t("Search recordings...", "Искать в записях..."), text: $viewModel.query)
                    .textFieldStyle(.plain)
                    .font(Typography.headingMedium)
                    .onSubmit {
                        performSearch()
                    }

                if !viewModel.query.isEmpty {
                    Button {
                        viewModel.query = ""
                        viewModel.results = []
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(Palette.textTertiary)
                    }
                    .buttonStyle(.plain)
                    .help(t("Clear search", "Очистить поиск"))
                }
            }
            .padding(Spacing.md)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .accessibilityIdentifier("search-bar")

            WaiTabBar(
                tabs: [
                    (t("Hybrid", "Комбинированный"), MacSearchViewModel.SearchMode.hybrid),
                    (t("Semantic", "По смыслу"), MacSearchViewModel.SearchMode.semantic),
                    (t("Full Text", "По тексту"), MacSearchViewModel.SearchMode.fts),
                ],
                selection: $viewModel.searchMode
            )
        }
        .frame(maxWidth: MacMainLayoutMetrics.searchContentMaxWidth, alignment: .leading)
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    @ViewBuilder
    private var searchResults: some View {
        if viewModel.isLoading {
            VStack {
                ProgressView(t("Searching...", "Ищем..."))
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if viewModel.results.isEmpty && !viewModel.query.isEmpty && viewModel.hasSearched {
            ContentUnavailableView(
                t("No Results", "Ничего не найдено"),
                systemImage: "magnifyingglass",
                description: Text(t(
                    "No recordings match \"\(viewModel.query)\".",
                    "По запросу \"\(viewModel.query)\" записей не найдено."
                ))
            )
        } else if viewModel.results.isEmpty {
            ContentUnavailableView(
                t("Search Your Recordings", "Поиск по записям"),
                systemImage: "magnifyingglass",
                description: Text(t(
                    "Search across all your recording transcripts.",
                    "Ищи по всем расшифровкам записей."
                ))
            )
            .accessibilityIdentifier("search-empty-state")
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Spacing.sm) {
                    Text(resultsCountText(viewModel.totalResults))
                        .font(Typography.label)
                        .foregroundStyle(Palette.textTertiary)
                        .padding(.horizontal, Spacing.lg)

                    ForEach(viewModel.results) { result in
                        SearchResultRow(result: result)
                    }
                }
                .padding(.vertical, Spacing.lg)
                .frame(maxWidth: MacMainLayoutMetrics.searchContentMaxWidth, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
        }
    }

    private func resultsCountText(_ count: Int) -> String {
        if OnboardingL10n.language(for: languageManager.current) == .russian {
            return "Найдено: \(count)"
        }
        return "\(count) result\(count == 1 ? "" : "s")"
    }

    private func performSearch() {
        guard !viewModel.query.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        Task {
            await viewModel.search(apiClient: appState.getAPIClient())
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

struct SearchResultRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let result: SearchResult

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack {
                Text(result.recordingTitle ?? t("Untitled", "Без названия"))
                    .font(Typography.headingMedium)
                    .lineLimit(1)

                Spacer()

                Text(String(format: "%.0f%%", result.score * 100))
                    .font(Typography.mono)
                    .foregroundStyle(Palette.textTertiary)
            }

            if let speaker = result.speaker {
                Text(speaker)
                    .font(Typography.label)
                    .foregroundStyle(Palette.accent)
            }

            Text(result.content)
                .font(Typography.reading)
                .lineSpacing(6)
                .lineLimit(3)
                .foregroundStyle(Palette.textSecondary)
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.md)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - ViewModel

@MainActor
class MacSearchViewModel: ObservableObject {
    enum SearchMode: Hashable {
        case hybrid, semantic, fts
    }

    @Published var query = ""
    @Published var searchMode: SearchMode = .hybrid
    @Published var results: [SearchResult] = []
    @Published var totalResults: Int = 0
    @Published var isLoading = false
    @Published var error: String?
    @Published var hasSearched = false

    func search(apiClient: APIClient) async {
        let trimmed = query.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }

        isLoading = true
        error = nil
        hasSearched = true

        do {
            let response: SearchResponse
            switch searchMode {
            case .hybrid:
                response = try await apiClient.search(query: trimmed)
            case .semantic:
                response = try await apiClient.semanticSearch(query: trimmed)
            case .fts:
                response = try await apiClient.fulltextSearch(query: trimmed)
            }
            results = response.results
            totalResults = response.total
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }

        isLoading = false
    }
}
