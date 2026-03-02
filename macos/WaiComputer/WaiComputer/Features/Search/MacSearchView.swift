import SwiftUI
import WaiComputerKit

struct MacSearchView: View {
    @EnvironmentObject var appState: MacAppState
    @StateObject private var viewModel = MacSearchViewModel()

    var body: some View {
        VStack(spacing: 0) {
            // Search bar + mode picker
            VStack(spacing: 12) {
                HStack {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)

                    TextField("Search recordings...", text: $viewModel.query)
                        .textFieldStyle(.plain)
                        .font(.body)
                        .onSubmit {
                            performSearch()
                        }

                    if !viewModel.query.isEmpty {
                        Button {
                            viewModel.query = ""
                            viewModel.results = []
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(10)
                .background(Color.gray.opacity(0.1))
                .cornerRadius(8)

                Picker("Search Mode", selection: $viewModel.searchMode) {
                    Text("Hybrid").tag(MacSearchViewModel.SearchMode.hybrid)
                    Text("Semantic").tag(MacSearchViewModel.SearchMode.semantic)
                    Text("Full Text").tag(MacSearchViewModel.SearchMode.fts)
                }
                .pickerStyle(.segmented)
            }
            .padding()

            Divider()

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
                    LazyVStack(alignment: .leading, spacing: 8) {
                        Text("\(viewModel.totalResults) result\(viewModel.totalResults == 1 ? "" : "s")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .padding(.horizontal)

                        ForEach(viewModel.results) { result in
                            SearchResultRow(result: result)
                        }
                    }
                    .padding()
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
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(result.recordingTitle ?? "Untitled")
                    .font(.headline)
                    .lineLimit(1)

                Spacer()

                // Relevance score
                Text(String(format: "%.0f%%", result.score * 100))
                    .font(.caption)
                    .fontWeight(.medium)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 2)
                    .background(scoreColor(result.score).opacity(0.15))
                    .foregroundStyle(scoreColor(result.score))
                    .clipShape(Capsule())
            }

            if let speaker = result.speaker {
                Text(speaker)
                    .font(.caption)
                    .fontWeight(.medium)
                    .foregroundStyle(.blue)
            }

            Text(result.content)
                .font(.body)
                .lineLimit(3)
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .background(Color.gray.opacity(0.04))
        .cornerRadius(8)
    }

    private func scoreColor(_ score: Double) -> Color {
        if score >= 0.7 { return .green }
        if score >= 0.4 { return .orange }
        return .gray
    }
}

// MARK: - ViewModel

@MainActor
class MacSearchViewModel: ObservableObject {
    enum SearchMode {
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
