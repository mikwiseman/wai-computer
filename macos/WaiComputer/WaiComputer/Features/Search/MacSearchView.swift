import SwiftUI
import WaiComputerKit

struct MacSearchView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var viewModel = MacSearchViewModel()
    @FocusState private var searchFieldFocused: Bool
    let onOpenRecording: (String) -> Void
    let onOpenItem: (String) -> Void

    init(
        onOpenRecording: @escaping (String) -> Void = { _ in },
        onOpenItem: @escaping (String) -> Void = { _ in }
    ) {
        self.onOpenRecording = onOpenRecording
        self.onOpenItem = onOpenItem
    }

    var body: some View {
        VStack(spacing: 0) {
            searchHeader

            WaiDivider()

            searchResults
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .onAppear { searchFieldFocused = true }
    }

    private var searchHeader: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(Palette.textTertiary)

                TextField(t("Search recordings...", "Искать в записях..."), text: $viewModel.query)
                    .textFieldStyle(.plain)
                    .font(Typography.headingMedium)
                    .focused($searchFieldFocused)
                    .onSubmit {
                        performSearch()
                    }
                    .accessibilityIdentifier("search-field")

                if !viewModel.query.isEmpty {
                    Button {
                        viewModel.clear()
                        searchFieldFocused = true
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(Palette.textTertiary)
                    }
                    .buttonStyle(.plain)
                    .help(t("Clear search", "Очистить поиск"))
                }

                Button {
                    performSearch()
                } label: {
                    Label(
                        MacSearchPresentation.searchButtonTitle(language: languageManager.current),
                        systemImage: "magnifyingglass"
                    )
                        .labelStyle(.titleAndIcon)
                }
                .buttonStyle(.borderedProminent)
                .disabled(viewModel.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading)
                .accessibilityIdentifier("search-submit-button")
            }
            .padding(Spacing.md)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .accessibilityIdentifier("search-bar")

            Picker("", selection: $viewModel.scope) {
                Text(t("Recordings", "Записи")).tag(SearchScope.recordings)
                Text(t("Everything", "Всё")).tag(SearchScope.everything)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            .onChangeCompat(of: viewModel.scope) {
                if viewModel.hasSearched { performSearch() }
            }
            .accessibilityIdentifier("search-scope")
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
        } else if let searchError = viewModel.error, !searchError.isEmpty {
            VStack(spacing: Spacing.md) {
                ContentUnavailableViewCompat(
                    t("Search Failed", "Не удалось выполнить поиск"),
                    systemImage: "exclamationmark.triangle",
                    description: Text(searchError)
                )
                Button(t("Try Again", "Повторить")) { performSearch() }
                    .buttonStyle(.bordered)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityIdentifier("search-error-state")
        } else if hasNoResults && !viewModel.query.isEmpty && viewModel.hasSearched {
            ContentUnavailableViewCompat(
                t("No Results", "Ничего не найдено"),
                systemImage: "magnifyingglass",
                description: Text(t(
                    "Nothing matches \"\(viewModel.query)\".",
                    "По запросу \"\(viewModel.query)\" ничего не найдено."
                ))
            )
        } else if hasNoResults {
            ContentUnavailableViewCompat(
                viewModel.scope == .everything
                    ? t("Search Everything", "Поиск по всему")
                    : t("Search Your Recordings", "Поиск по записям"),
                systemImage: "magnifyingglass",
                description: Text(
                    viewModel.scope == .everything
                        ? t("Search across recordings and everything you've added.",
                            "Ищите по записям и всему, что вы добавили.")
                        : t("Search across all your recording transcripts.",
                            "Ищи по всем расшифровкам записей.")
                )
            )
            .accessibilityIdentifier("search-empty-state")
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Spacing.sm) {
                    Text(resultsCountText(
                        shown: viewModel.scope == .everything
                            ? viewModel.unifiedResults.count
                            : viewModel.results.count,
                        total: viewModel.totalResults
                    ))
                        .font(Typography.label)
                        .foregroundStyle(Palette.textTertiary)
                        .padding(.horizontal, Spacing.lg)

                    if viewModel.scope == .everything {
                        ForEach(viewModel.unifiedResults) { hit in
                            UnifiedResultRow(hit: hit) {
                                openUnifiedHit(hit)
                            }
                        }
                    } else {
                        ForEach(viewModel.results) { result in
                            SearchResultRow(result: result) {
                                onOpenRecording(result.recordingId)
                            }
                        }
                    }
                }
                .padding(.vertical, Spacing.lg)
                .frame(maxWidth: MacMainLayoutMetrics.searchContentMaxWidth, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
        }
    }

    private var hasNoResults: Bool {
        viewModel.scope == .everything ? viewModel.unifiedResults.isEmpty : viewModel.results.isEmpty
    }

    /// Route a unified hit: recordings open in the detail pane; items open the
    /// material detail (previously this dropped the id and just landed in Inbox).
    private func openUnifiedHit(_ hit: UnifiedHit) {
        if hit.sourceKind == "recording" {
            onOpenRecording(hit.parentId)
        } else {
            onOpenItem(hit.parentId)
        }
    }

    private func resultsCountText(shown: Int, total: Int) -> String {
        let russian = OnboardingL10n.language(for: languageManager.current) == .russian
        // Be honest when more results exist than are shown (no pagination yet).
        if shown < total {
            return russian ? "Показано \(shown) из \(total)" : "Showing \(shown) of \(total)"
        }
        return russian ? "Найдено: \(total)" : "\(total) result\(total == 1 ? "" : "s")"
    }

    private func performSearch() {
        guard !viewModel.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        #if DEBUG
        if let response = appState.uiTestSearchResponse(query: viewModel.query) {
            viewModel.applySearchResponse(response)
            return
        }
        #endif
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
    let onOpen: () -> Void

    var body: some View {
        Button(action: onOpen) {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                HStack {
                    Text(result.recordingTitle ?? t("Untitled", "Без названия"))
                        .font(Typography.headingMedium)
                        .lineLimit(1)

                    Spacer()
                }

                if let speaker = displaySpeaker {
                    Text(speaker)
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                }

                Text(result.content)
                    .font(Typography.reading)
                    .lineSpacing(6)
                    .lineLimit(3)
                    .foregroundStyle(Palette.textSecondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.md)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .accessibilityIdentifier(MacSearchPresentation.resultRowIdentifier(recordingId: result.recordingId))
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

/// A unified-search hit row (recording or item), shown in the "Everything" scope.
struct UnifiedResultRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let hit: UnifiedHit
    let onOpen: () -> Void

    var body: some View {
        Button(action: onOpen) {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                HStack(spacing: Spacing.xs) {
                    Image(systemName: hit.sourceKind == "recording" ? "waveform" : "doc.text")
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textSecondary)
                    Text(hit.title ?? t("Untitled", "Без названия"))
                        .font(Typography.headingMedium)
                        .lineLimit(1)
                    Spacer()
                    Text(hit.kind.uppercased())
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                }

                Text(hit.snippet)
                    .font(Typography.reading)
                    .lineSpacing(6)
                    .lineLimit(3)
                    .foregroundStyle(Palette.textSecondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.md)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityIdentifier("unified-result-\(hit.chunkId)")
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

enum MacSearchPresentation {
    static func searchButtonTitle(language selection: LanguageManager.SupportedLanguage) -> String {
        OnboardingL10n.text("Search", "Поиск", language: selection)
    }

    static func resultRowIdentifier(recordingId: String) -> String {
        "search-result-row-\(recordingId)"
    }

}

// MARK: - ViewModel

enum SearchScope: Hashable {
    case recordings
    case everything
}

class MacSearchViewModel: ObservableObject {
    @Published var query = ""
    @Published var results: [SearchResult] = []
    @Published var unifiedResults: [UnifiedHit] = []
    @Published var totalResults: Int = 0
    @Published var isLoading = false
    @Published var error: String?
    @Published var hasSearched = false
    @Published var scope: SearchScope = .recordings

    func applySearchResponse(_ response: SearchResponse) {
        error = nil
        hasSearched = true
        isLoading = false
        results = response.results
        totalResults = response.total
    }

    func search(apiClient: APIClient) async {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        isLoading = true
        error = nil
        hasSearched = true

        do {
            switch scope {
            case .recordings:
                let response = try await apiClient.search(query: trimmed)
                results = response.results
                unifiedResults = []
                totalResults = response.total
            case .everything:
                let response = try await apiClient.unifiedSearch(query: trimmed)
                unifiedResults = response.results
                results = []
                totalResults = response.total
            }
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }

        isLoading = false
    }

    /// Reset every result/error/searched flag so clearing the field returns a
    /// clean slate. Previously only `query` + `results` were reset, leaving
    /// `unifiedResults`, `totalResults`, and a stale error on screen.
    func clear() {
        query = ""
        results = []
        unifiedResults = []
        totalResults = 0
        error = nil
        hasSearched = false
    }
}
