import SwiftUI
import WaiSayKit

struct SearchView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var viewModel = SearchViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Search bar
                HStack {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)

                    TextField("Search recordings...", text: $viewModel.query)
                        .textFieldStyle(.plain)
                        .autocapitalization(.none)
                        .submitLabel(.search)
                        .onSubmit {
                            Task {
                                await viewModel.search(apiClient: appState.getAPIClient())
                            }
                        }

                    if !viewModel.query.isEmpty {
                        Button(action: { viewModel.query = "" }) {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .padding()
                .background(Color.gray.opacity(0.1))
                .cornerRadius(12)
                .padding()

                // Search mode
                Picker("Mode", selection: $viewModel.searchMode) {
                    Text("Hybrid").tag(SearchViewModel.SearchMode.hybrid)
                    Text("Semantic").tag(SearchViewModel.SearchMode.semantic)
                    Text("Text").tag(SearchViewModel.SearchMode.fulltext)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)

                // Results
                if viewModel.isLoading {
                    ProgressView()
                        .padding(.top, 32)
                    Spacer()
                } else if viewModel.results.isEmpty && !viewModel.query.isEmpty && viewModel.hasSearched {
                    ContentUnavailableView.search(text: viewModel.query)
                    Spacer()
                } else if viewModel.results.isEmpty {
                    ContentUnavailableView(
                        "Search Your Brain",
                        systemImage: "brain.head.profile",
                        description: Text("Find anything in your recordings")
                    )
                    Spacer()
                } else {
                    resultsList
                }
            }
            .navigationTitle("Search")
        }
    }

    private var resultsList: some View {
        List {
            ForEach(viewModel.results) { result in
                NavigationLink(destination: RecordingDetailView(recording: Recording(
                    id: result.recordingId,
                    title: result.recordingTitle,
                    type: result.recordingType,
                    createdAt: Date()
                ))) {
                    SearchResultRow(result: result)
                }
            }
        }
    }
}

struct SearchResultRow: View {
    let result: SearchResult

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(result.recordingTitle ?? "Untitled")
                    .font(.headline)

                Spacer()

                Text(String(format: "%.0f%%", result.score * 100))
                    .font(.caption)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(scoreColor.opacity(0.2))
                    .foregroundStyle(scoreColor)
                    .cornerRadius(4)
            }

            if let speaker = result.speaker {
                Text(speaker)
                    .font(.caption)
                    .foregroundStyle(.blue)
            }

            Text(result.content)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(3)
        }
        .padding(.vertical, 4)
    }

    private var scoreColor: Color {
        if result.score > 0.7 {
            return .green
        } else if result.score > 0.4 {
            return .orange
        } else {
            return .gray
        }
    }
}

@MainActor
class SearchViewModel: ObservableObject {
    @Published var query = ""
    @Published var results: [SearchResult] = []
    @Published var isLoading = false
    @Published var hasSearched = false
    @Published var searchMode: SearchMode = .hybrid

    enum SearchMode {
        case hybrid
        case semantic
        case fulltext
    }

    func search(apiClient: APIClient) async {
        guard !query.isEmpty else {
            results = []
            return
        }

        isLoading = true
        hasSearched = true

        do {
            let response: SearchResponse
            switch searchMode {
            case .hybrid:
                response = try await apiClient.search(query: query)
            case .semantic:
                response = try await apiClient.semanticSearch(query: query)
            case .fulltext:
                response = try await apiClient.fulltextSearch(query: query)
            }
            results = response.results
        } catch {
            results = []
        }

        isLoading = false
    }
}

#Preview {
    SearchView()
        .environmentObject(AppState())
}
