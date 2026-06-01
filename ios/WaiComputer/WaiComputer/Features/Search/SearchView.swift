import SwiftUI
import WaiComputerKit

// MARK: - Search Scope

/// Search mode exposed as a `.searchScopes` segmented control on the Library
/// `.searchable` surface. Mirrors the macOS search-mode concept while staying
/// iOS-idiomatic (the picker lives in the search bar, not a standalone screen).
enum LibrarySearchScope: String, CaseIterable, Identifiable {
    case hybrid
    case semantic
    case fulltext

    var id: String { rawValue }

    func label(language: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .hybrid:
            return OnboardingL10n.text("Hybrid", "Гибрид", language: language)
        case .semantic:
            return OnboardingL10n.text("Semantic", "Смысловой", language: language)
        case .fulltext:
            return OnboardingL10n.text("Text", "Текст", language: language)
        }
    }
}

// MARK: - Search Results (hosted by LibraryView .searchable)

/// The content shown over the Library list while the user is searching.
/// Rendered by `LibraryView` when the search field is active or a query has
/// been committed. Behaviour mirrors `MacSearchView`: explicit submit button,
/// results-count label, dedicated empty / loading / error states, localized
/// speaker chips, and accessibility identifiers for UI tests.
struct LibrarySearchResults: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @ObservedObject var viewModel: SearchViewModel
    let onSubmit: () -> Void
    let onOpenRecording: (SearchResult) -> Void

    var body: some View {
        VStack(spacing: 0) {
            // Mode picker mirrors macOS search modes. `.searchScopes` only
            // shows while the field is focused, so an inline picker keeps the
            // control reachable once a query is committed too.
            Picker(t("Search Mode", "Режим поиска"), selection: $viewModel.searchMode) {
                ForEach(LibrarySearchScope.allCases) { scope in
                    Text(scope.label(language: languageManager.current)).tag(scope)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, Spacing.lg)
            .padding(.top, Spacing.md)
            .accessibilityIdentifier("search-mode-picker")

            Button(action: onSubmit) {
                Label(
                    t("Search", "Поиск"),
                    systemImage: "magnifyingglass"
                )
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(Palette.accent)
            .disabled(viewModel.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading)
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.md)
            .accessibilityIdentifier("search-submit-button")

            content
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Color(uiColor: .systemBackground))
        .accessibilityIdentifier("search-bar")
    }

    @ViewBuilder
    private var content: some View {
        if let error = viewModel.error {
            ContentUnavailableView {
                Label(t("Search Failed", "Ошибка поиска"), systemImage: "exclamationmark.triangle")
            } description: {
                Text(error)
            } actions: {
                Button(t("Try Again", "Повторить"), action: onSubmit)
                    .buttonStyle(.borderedProminent)
                    .tint(Palette.accent)
                    .disabled(viewModel.isLoading)
            }
            .accessibilityIdentifier("search-error-state")
            Spacer(minLength: 0)
        } else if viewModel.isLoading {
            ProgressView(t("Searching...", "Ищем..."))
                .padding(.top, Spacing.xxl)
                .accessibilityIdentifier("search-loading")
            Spacer(minLength: 0)
        } else if viewModel.results.isEmpty && viewModel.hasSearched {
            ContentUnavailableView(
                t("No Results", "Ничего не найдено"),
                systemImage: "magnifyingglass",
                description: Text(String(
                    format: t(
                        "No recordings match \u{201C}%@\u{201D}.",
                        "По запросу \u{201C}%@\u{201D} записей не найдено."
                    ),
                    viewModel.query
                ))
            )
            .accessibilityIdentifier("search-no-results-state")
            Spacer(minLength: 0)
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
            Spacer(minLength: 0)
        } else {
            resultsList
        }
    }

    private var resultsList: some View {
        List {
            Section {
                ForEach(viewModel.results) { result in
                    Button {
                        onOpenRecording(result)
                    } label: {
                        SearchResultRow(result: result)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier(SearchPresentation.resultRowIdentifier(recordingId: result.recordingId))
                }
            } header: {
                Text(resultsCountText(viewModel.totalResults))
                    .accessibilityIdentifier("search-results-count")
            }
        }
        .listStyle(.plain)
    }

    private func resultsCountText(_ count: Int) -> String {
        if OnboardingL10n.language(for: languageManager.current) == .russian {
            return "Найдено: \(count)"
        }
        return "\(count) result\(count == 1 ? "" : "s")"
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Result Row

struct SearchResultRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let result: SearchResult

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                Text(result.recordingTitle ?? t("Untitled", "Без названия"))
                    .font(.headline)
                    .lineLimit(1)

                Spacer()

                Text(String(format: "%.0f%%", result.score * 100))
                    .font(.caption)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(scoreColor.opacity(0.2))
                    .foregroundStyle(scoreColor)
                    .cornerRadius(4)
            }

            if let speaker = displaySpeaker {
                Text(speaker)
                    .font(.caption)
                    .foregroundStyle(Palette.accent)
            }

            Text(result.content)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(3)
        }
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }

    private var displaySpeaker: String? {
        SpeakerLabelCopy.userFacingLabel(result.speaker, languageCode: speakerLanguageCode)
    }

    private var speakerLanguageCode: String {
        switch languageManager.current {
        case .followSystem:
            return languageManager.preferredLocale.identifier
        case .english, .russian:
            return languageManager.current.rawValue
        }
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Presentation helpers

enum SearchPresentation {
    static func resultRowIdentifier(recordingId: String) -> String {
        "search-result-row-\(recordingId)"
    }
}

// MARK: - ViewModel

@MainActor
class SearchViewModel: ObservableObject {
    @Published var query = ""
    @Published var results: [SearchResult] = []
    @Published var totalResults: Int = 0
    @Published var isLoading = false
    @Published var hasSearched = false
    @Published var error: String?
    @Published var searchMode: LibrarySearchScope = .hybrid

    /// Inject a deterministic response (DEBUG screenshot/UI-test fixture)
    /// without hitting the network. Mirrors `MacSearchViewModel`.
    func applySearchResponse(_ response: SearchResponse) {
        error = nil
        hasSearched = true
        isLoading = false
        results = response.results
        totalResults = response.total
    }

    func reset() {
        results = []
        totalResults = 0
        hasSearched = false
        error = nil
        isLoading = false
    }

    func search(apiClient: APIClient) async {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
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
            case .fulltext:
                response = try await apiClient.fulltextSearch(query: trimmed)
            }
            results = response.results
            totalResults = response.total
        } catch {
            results = []
            totalResults = 0
            self.error = error.userFacingMessage(context: .generic)
        }

        isLoading = false
    }
}

#Preview {
    NavigationStack {
        LibrarySearchResults(
            viewModel: {
                let vm = SearchViewModel()
                vm.query = "dashboard"
                return vm
            }(),
            onSubmit: {},
            onOpenRecording: { _ in }
        )
        .navigationTitle("Search")
    }
    .environmentObject(AppState())
    .environmentObject(LanguageManager.shared)
}
