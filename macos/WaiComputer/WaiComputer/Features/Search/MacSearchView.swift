import SwiftUI
import WaiComputerKit

struct MacSearchView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var viewModel = MacSearchViewModel()
    let onOpenRecording: (String) -> Void

    init(onOpenRecording: @escaping (String) -> Void = { _ in }) {
        self.onOpenRecording = onOpenRecording
    }

    var body: some View {
        VStack(spacing: 0) {
            searchHeader

            WaiDivider()

            searchResults
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
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
                    .accessibilityIdentifier("search-field")

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
            ContentUnavailableViewCompat(
                t("No Results", "Ничего не найдено"),
                systemImage: "magnifyingglass",
                description: Text(t(
                    "No recordings match \"\(viewModel.query)\".",
                    "По запросу \"\(viewModel.query)\" записей не найдено."
                ))
            )
        } else if viewModel.results.isEmpty {
            ContentUnavailableViewCompat(
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
                        SearchResultRow(result: result) {
                            onOpenRecording(result.recordingId)
                        }
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
                        .foregroundStyle(Palette.accent)
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

enum MacSearchPresentation {
    static func searchButtonTitle(language selection: LanguageManager.SupportedLanguage) -> String {
        OnboardingL10n.text("Search", "Поиск", language: selection)
    }

    static func resultRowIdentifier(recordingId: String) -> String {
        "search-result-row-\(recordingId)"
    }

}

// MARK: - ViewModel

@MainActor
class MacSearchViewModel: ObservableObject {
    @Published var query = ""
    @Published var results: [SearchResult] = []
    @Published var totalResults: Int = 0
    @Published var isLoading = false
    @Published var error: String?
    @Published var hasSearched = false

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
            let response = try await apiClient.search(query: trimmed)
            results = response.results
            totalResults = response.total
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }

        isLoading = false
    }
}
