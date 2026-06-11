import SwiftUI
import WaiComputerKit

struct MacSearchView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var viewModel = MacSearchViewModel()
    @FocusState private var searchFieldFocused: Bool
    let onOpenRecording: (String) -> Void
    let onOpenItem: (String) -> Void
    let onOpenChat: (String) -> Void

    init(
        onOpenRecording: @escaping (String) -> Void = { _ in },
        onOpenItem: @escaping (String) -> Void = { _ in },
        onOpenChat: @escaping (String) -> Void = { _ in }
    ) {
        self.onOpenRecording = onOpenRecording
        self.onOpenItem = onOpenItem
        self.onOpenChat = onOpenChat
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

                TextField(
                    viewModel.scope == .everything
                        ? t("Search everything...", "Искать везде...")
                        : t("Search recordings...", "Искать в записях..."),
                    text: $viewModel.query
                )
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

            Picker(t("Search scope", "Область поиска"), selection: $viewModel.scope) {
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
            .accessibilityLabel(t("Search scope", "Область поиска"))
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
                    "Nothing matches \"\(viewModel.lastSubmittedQuery)\".",
                    "По запросу \"\(viewModel.lastSubmittedQuery)\" ничего не найдено."
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
                            "Ищи по записям и всему, что добавлено.")
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

    /// Route a unified hit: recordings open in the detail pane; chats open the
    /// Wai conversation (previously they misrouted to the item detail and 404'd);
    /// everything else opens the material detail.
    private func openUnifiedHit(_ hit: UnifiedHit) {
        switch hit.sourceKind {
        case "recording":
            onOpenRecording(hit.parentId)
        case "chat":
            onOpenChat(hit.parentId)
        default:
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
    @State private var isHovered = false

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
            .background(isHovered ? Palette.surfaceHover : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .onHover { isHovered = $0 }
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
    @State private var isHovered = false

    var body: some View {
        Button(action: onOpen) {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                HStack(spacing: Spacing.xs) {
                    Image(systemName: sourceIcon)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textSecondary)
                    Text(hit.title ?? t("Untitled", "Без названия"))
                        .font(Typography.headingMedium)
                        .lineLimit(1)
                    Spacer()
                    Text(localizedKind)
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                        .textCase(.uppercase)
                        .tracking(1.2)
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
            .background(isHovered ? Palette.surfaceHover : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .frame(maxWidth: .infinity, alignment: .leading)
        .onHover { isHovered = $0 }
        .accessibilityIdentifier("unified-result-\(hit.chunkId)")
    }

    /// Per-source icon: chats match the inbox chat rows ("sparkles") instead of
    /// masquerading as documents.
    private var sourceIcon: String {
        switch hit.sourceKind {
        case "recording": return "waveform"
        case "chat": return "sparkles"
        default: return "doc.text"
        }
    }

    /// The backend emits raw English kinds (meeting/note/chat/...); map the
    /// known ones through t() so the RU UI doesn't badge English enums.
    private var localizedKind: String {
        switch hit.kind.lowercased() {
        case "meeting": return t("Meeting", "Встреча")
        case "note": return t("Note", "Заметка")
        case "chat": return t("Chat", "Чат")
        case "article": return t("Article", "Статья")
        case "reflection": return t("Reflection", "Размышление")
        default: return hit.kind
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

enum SearchScope: Hashable {
    case recordings
    case everything
}

@MainActor
class MacSearchViewModel: ObservableObject {
    @Published var query = ""
    /// The query that actually ran. Empty-state copy quotes this instead of the
    /// live field text, which the user may have edited since submitting.
    @Published private(set) var lastSubmittedQuery = ""
    @Published var results: [SearchResult] = []
    @Published var unifiedResults: [UnifiedHit] = []
    @Published var totalResults: Int = 0
    @Published var isLoading = false
    @Published var error: String?
    @Published var hasSearched = false
    @Published var scope: SearchScope = .recordings

    private var searchTask: Task<Void, Never>?

    func applySearchResponse(_ response: SearchResponse) {
        lastSubmittedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        error = nil
        hasSearched = true
        isLoading = false
        results = response.results
        totalResults = response.total
    }

    func search(apiClient: APIClient) async {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // Latest submission wins: cancel any in-flight search so a slow older
        // response can't land after — and overwrite — a newer one.
        searchTask?.cancel()
        let task = Task { await self.runSearch(query: trimmed, apiClient: apiClient) }
        searchTask = task
        await task.value
    }

    private func runSearch(query trimmed: String, apiClient: APIClient) async {
        isLoading = true
        error = nil
        hasSearched = true
        lastSubmittedQuery = trimmed

        do {
            switch scope {
            case .recordings:
                let response = try await apiClient.search(query: trimmed)
                guard !Task.isCancelled else { return }
                results = response.results
                unifiedResults = []
                totalResults = response.total
            case .everything:
                let response = try await apiClient.unifiedSearch(query: trimmed)
                guard !Task.isCancelled else { return }
                unifiedResults = response.results
                results = []
                totalResults = response.total
            }
        } catch {
            // A cancelled request must stay silent: the newer search owns the
            // spinner and the error surface now, and the cancellation error
            // itself must never paint "Search Failed".
            guard !Task.isCancelled else { return }
            self.error = error.userFacingMessage(context: .generic)
        }

        guard !Task.isCancelled else { return }
        isLoading = false
    }

    /// Reset every result/error/searched flag so clearing the field returns a
    /// clean slate. Previously only `query` + `results` were reset, leaving
    /// `unifiedResults`, `totalResults`, and a stale error on screen. Also
    /// cancels any in-flight search so its response can't repopulate the
    /// cleared screen.
    func clear() {
        searchTask?.cancel()
        query = ""
        lastSubmittedQuery = ""
        results = []
        unifiedResults = []
        totalResults = 0
        error = nil
        hasSearched = false
        isLoading = false
    }
}
