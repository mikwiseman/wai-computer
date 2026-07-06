import SwiftUI
import WaiComputerKit

enum MacSearchViewMode: Equatable {
    case search
    case wai
}

struct MacSearchView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var viewModel = MacSearchViewModel()
    @State private var activeChatId: String?
    @FocusState private var searchFieldFocused: Bool
    let mode: MacSearchViewMode
    let recordings: [Recording]
    let initialChatId: String?
    let onOpenRecording: (String) -> Void
    let onOpenItem: (String) -> Void
    let onOpenChat: (String) -> Void
    let onInitialChatConsumed: () -> Void

    init(
        mode: MacSearchViewMode = .search,
        recordings: [Recording],
        initialChatId: String? = nil,
        onOpenRecording: @escaping (String) -> Void = { _ in },
        onOpenItem: @escaping (String) -> Void = { _ in },
        onOpenChat: @escaping (String) -> Void = { _ in },
        onInitialChatConsumed: @escaping () -> Void = {}
    ) {
        self.mode = mode
        self.recordings = recordings
        self.initialChatId = initialChatId
        self.onOpenRecording = onOpenRecording
        self.onOpenItem = onOpenItem
        self.onOpenChat = onOpenChat
        self.onInitialChatConsumed = onInitialChatConsumed
    }

    var body: some View {
        Group {
            switch mode {
            case .search:
                searchPane
            case .wai:
                waiPane
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear {
            if mode == .search {
                searchFieldFocused = true
            }
            consumeInitialChatIfNeeded(initialChatId)
        }
        .onChangeCompat(of: initialChatId) { _, chatId in
            consumeInitialChatIfNeeded(chatId)
        }
    }

    private var searchPane: some View {
        VStack(spacing: 0) {
            searchHeader

            WaiDivider()

            searchResults
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    private var waiPane: some View {
        CompanionView(
            apiClient: appState.getAPIClient(),
            recordings: recordings,
            initialChatId: activeChatId,
            onTurnCompleted: { completion in
                MacWaiTaskNotificationCenter.shared.notifyTaskFinished(
                    title: t("Wai finished", "Wai закончил"),
                    body: completion.preview ?? t("Your Wai task is ready.", "Задача Wai готова."),
                    chatId: completion.chatId
                )
            },
            onOpenCitation: { recordingId, _ in
                onOpenRecording(recordingId)
            }
        )
        .environment(\.locale, MacDateFormatting.locale(for: languageManager.current))
        .companionAccentColor(Palette.accent)
    }

    private var searchHeader: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(Palette.textTertiary)

                TextField(
                    t("Search your second brain...", "Искать по второму мозгу..."),
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
            .clipShape(RoundedRectangle(cornerRadius: Radius.md))
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
                t("Search Your Second Brain", "Поиск по второму мозгу"),
                systemImage: "magnifyingglass",
                description: Text(
                    t(
                        "Search everything you've added.",
                        "Ищи по всему добавленному."
                    )
                )
            )
            .accessibilityIdentifier("search-empty-state")
        } else {
            List {
                Text(resultsCountText(
                    shown: viewModel.unifiedResults.count,
                    total: viewModel.totalResults
                ))
                .font(Typography.label)
                .foregroundStyle(Palette.textTertiary)
                .padding(.horizontal, Spacing.lg)
                .padding(.top, Spacing.lg)
                .searchResultListRow()

                ForEach(viewModel.unifiedResults) { hit in
                    UnifiedResultRow(hit: hit) {
                        openUnifiedHit(hit)
                    }
                    .searchResultListRow()
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .frame(maxWidth: MacMainLayoutMetrics.searchContentMaxWidth, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .accessibilityIdentifier("search-results-list")
        }
    }

    private var hasNoResults: Bool {
        viewModel.unifiedResults.isEmpty
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
        if let response = appState.uiTestUnifiedSearchResponse(query: viewModel.query) {
            viewModel.applyUnifiedSearchResponse(response)
            return
        }
        #endif
        Task {
            await viewModel.search(apiClient: appState.getAPIClient())
        }
    }

    private func consumeInitialChatIfNeeded(_ chatId: String?) {
        guard mode == .wai, let chatId, activeChatId != chatId else { return }
        activeChatId = chatId
        onInitialChatConsumed()
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private extension View {
    func searchResultListRow() -> some View {
        self
            .listRowInsets(EdgeInsets())
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
    }
}

/// A unified-search hit row (recording, material, or chat).
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
            .clipShape(RoundedRectangle(cornerRadius: Radius.md, style: .continuous))
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
}

// MARK: - ViewModel

@MainActor
class MacSearchViewModel: ObservableObject {
    @Published var query = ""
    /// The query that actually ran. Empty-state copy quotes this instead of the
    /// live field text, which the user may have edited since submitting.
    @Published private(set) var lastSubmittedQuery = ""
    @Published var unifiedResults: [UnifiedHit] = []
    @Published var totalResults: Int = 0
    @Published var isLoading = false
    @Published var error: String?
    @Published var hasSearched = false

    private var searchTask: Task<Void, Never>?

    func applyUnifiedSearchResponse(_ response: UnifiedSearchResponse) {
        lastSubmittedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        error = nil
        hasSearched = true
        isLoading = false
        unifiedResults = response.results
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
            let response = try await apiClient.unifiedSearch(query: trimmed)
            guard !Task.isCancelled else { return }
            unifiedResults = response.results
            totalResults = response.total
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
        unifiedResults = []
        totalResults = 0
        error = nil
        hasSearched = false
        isLoading = false
    }
}
