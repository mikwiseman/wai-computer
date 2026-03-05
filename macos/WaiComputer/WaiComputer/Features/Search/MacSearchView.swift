import SwiftUI
import WaiComputerKit

struct MacSearchView: View {
    @EnvironmentObject var appState: MacAppState
    @StateObject private var viewModel = MacSearchViewModel()

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: Spacing.md) {
                // Large search input
                HStack(spacing: Spacing.sm) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(Palette.textTertiary)

                    TextField("Search recordings...", text: $viewModel.query)
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
                    }
                }
                .padding(Spacing.md)
                .background(Palette.surfaceSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8))

                // Mode tabs (text-based)
                WaiTabBar(
                    tabs: [
                        ("Hybrid", MacSearchViewModel.SearchMode.hybrid),
                        ("Semantic", MacSearchViewModel.SearchMode.semantic),
                        ("Full Text", MacSearchViewModel.SearchMode.fts),
                    ],
                    selection: $viewModel.searchMode
                )
            }
            .padding(Spacing.lg)

            WaiDivider()

            // Results
            if viewModel.isLoading {
                Spacer()
                ProgressView("Searching...")
                Spacer()
            } else if viewModel.results.isEmpty && !viewModel.query.isEmpty && viewModel.hasSearched {
                ContentUnavailableView.search(text: viewModel.query)
            } else if viewModel.results.isEmpty {
                ContentUnavailableView(
                    "Search Your Recordings",
                    systemImage: "magnifyingglass",
                    description: Text("Search across all your recording transcripts.")
                )
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: Spacing.sm) {
                        Text("\(viewModel.totalResults) result\(viewModel.totalResults == 1 ? "" : "s")")
                            .font(Typography.label)
                            .foregroundStyle(Palette.textTertiary)
                            .padding(.horizontal, Spacing.lg)

                        ForEach(viewModel.results) { result in
                            SearchResultRow(result: result)
                        }
                    }
                    .padding(.vertical, Spacing.lg)
                }
            }
        }
    }

    private func performSearch() {
        guard !viewModel.query.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        Task {
            await viewModel.search(apiClient: appState.getAPIClient())
        }
    }
}

struct SearchResultRow: View {
    let result: SearchResult

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack {
                Text(result.recordingTitle ?? "Untitled")
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
            self.error = error.localizedDescription
        }

        isLoading = false
    }
}
