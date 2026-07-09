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

// MARK: - Standalone Unified Search

/// First-class iPad workspace search. Mirrors the macOS Search tool more
/// closely than the compact Library search: it queries unified search across
/// recordings and captured materials, then routes each hit to the right detail
/// surface.
struct IOSUnifiedSearchView: View {
    @EnvironmentObject private var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @StateObject private var viewModel = IOSUnifiedSearchViewModel()
    @FocusState private var searchFieldFocused: Bool
    @State private var selectedHit: UnifiedHit?

    let apiClient: APIClient

    var body: some View {
        NavigationStack {
            Group {
                if isRegularWidth {
                    regularSearchLayout
                } else {
                    compactSearchLayout
                }
            }
            .navigationTitle(t("Search", "Поиск"))
            .navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)
            .background(Color(uiColor: .systemGroupedBackground))
            .onAppear {
                searchFieldFocused = true
            }
            .onChange(of: viewModel.results.map(\.id)) { _, resultIds in
                guard let selectedHit else { return }
                if !resultIds.contains(selectedHit.id) {
                    self.selectedHit = nil
                }
            }
        }
        .accessibilityIdentifier("ios-unified-search-view")
    }

    private var isRegularWidth: Bool {
        horizontalSizeClass == .regular
    }

    private var compactSearchLayout: some View {
        VStack(spacing: 0) {
            searchHeader
            Divider()
            searchContent
        }
    }

    private var regularSearchLayout: some View {
        HStack(spacing: 0) {
            VStack(spacing: 0) {
                searchHeader
                Divider()
                searchContent
            }
            .frame(minWidth: 340, idealWidth: 430, maxWidth: 520, maxHeight: .infinity, alignment: .topLeading)
            .background(Palette.surfaceSubtle)
            .accessibilityIdentifier("ios-unified-search-results-pane")

            Divider()

            regularDetailPane
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(Color(uiColor: .systemGroupedBackground))
                .accessibilityIdentifier("ios-unified-search-detail-pane")
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityIdentifier("ios-unified-search-regular-layout")
    }

    private var searchHeader: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(Palette.textTertiary)

            TextField(
                t("Search your second brain…", "Искать по второму мозгу…"),
                text: $viewModel.query
            )
            .textFieldStyle(.plain)
            .font(Typography.headingMedium)
            .focused($searchFieldFocused)
            .onSubmit(performSearch)
            .accessibilityIdentifier("ios-unified-search-field")

            if !viewModel.query.isEmpty {
                Button {
                    clearSearch()
                    searchFieldFocused = true
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(Palette.textTertiary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(t("Clear search", "Очистить поиск"))
            }

            Button(action: performSearch) {
                Label(t("Search", "Поиск"), systemImage: "magnifyingglass")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.borderedProminent)
            .tint(Palette.accent)
            .disabled(viewModel.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading)
            .accessibilityIdentifier("ios-unified-search-submit-button")
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .padding(Spacing.lg)
        .frame(maxWidth: 760, alignment: .leading)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    @ViewBuilder
    private var regularDetailPane: some View {
        if let selectedHit {
            destination(for: selectedHit)
        } else {
            IOSUnifiedSearchDetailPlaceholder(
                hasResults: !viewModel.results.isEmpty,
                hasSearched: viewModel.hasSearched
            )
            .environmentObject(languageManager)
        }
    }

    @ViewBuilder
    private var searchContent: some View {
        if viewModel.isLoading {
            ProgressView(t("Searching…", "Ищем…"))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier("ios-unified-search-loading")
        } else if let error = viewModel.error {
            ContentUnavailableView {
                Label(t("Search Failed", "Не удалось выполнить поиск"), systemImage: "exclamationmark.triangle")
            } description: {
                Text(error)
            } actions: {
                Button(t("Try Again", "Повторить"), action: performSearch)
                    .buttonStyle(.borderedProminent)
                    .tint(Palette.accent)
            }
            .accessibilityIdentifier("ios-unified-search-error")
        } else if viewModel.results.isEmpty && viewModel.hasSearched {
            ContentUnavailableView(
                t("No Results", "Ничего не найдено"),
                systemImage: "magnifyingglass",
                description: Text(t(
                    "Nothing matches \"\(viewModel.lastSubmittedQuery)\".",
                    "По запросу \"\(viewModel.lastSubmittedQuery)\" ничего не найдено."
                ))
            )
            .accessibilityIdentifier("ios-unified-search-no-results")
        } else if viewModel.results.isEmpty {
            ContentUnavailableView(
                t("Search Your Second Brain", "Поиск по второму мозгу"),
                systemImage: "magnifyingglass"
            )
            .accessibilityIdentifier("ios-unified-search-empty")
        } else {
            List {
                Section {
                    Text(resultsCountText(shown: viewModel.results.count, total: viewModel.totalResults))
                        .font(Typography.label)
                        .foregroundStyle(Palette.textTertiary)
                        .listRowSeparator(.hidden)
                        .listRowBackground(Color.clear)

                    ForEach(viewModel.results) { hit in
                        resultRow(for: hit)
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .frame(maxWidth: 760, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .accessibilityIdentifier("ios-unified-search-results-list")
        }
    }

    @ViewBuilder
    private func resultRow(for hit: UnifiedHit) -> some View {
        if isRegularWidth {
            Button {
                selectedHit = hit
            } label: {
                UnifiedSearchHitRow(hit: hit)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .listRowSeparator(.hidden)
            .listRowBackground(isSelected(hit) ? Palette.accentSubtle : Color.clear)
            .accessibilityIdentifier("ios-unified-result-\(hit.chunkId)")
        } else {
            NavigationLink {
                destination(for: hit)
            } label: {
                UnifiedSearchHitRow(hit: hit)
            }
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
            .accessibilityIdentifier("ios-unified-result-\(hit.chunkId)")
        }
    }

    @ViewBuilder
    private func destination(for hit: UnifiedHit) -> some View {
        switch hit.sourceKind {
        case "recording":
            if let recordingType = RecordingType(rawValue: hit.kind) {
                RecordingDetailView(recording: Recording(
                    id: hit.parentId,
                    title: hit.title,
                    type: recordingType,
                    createdAt: Date()
                ))
            } else {
                ContentUnavailableView(
                    t("Unknown Recording Type", "Неизвестный тип записи"),
                    systemImage: "exclamationmark.triangle",
                    description: Text(hit.kind)
                )
            }
        case "chat":
            WaiHomeView(initialChatId: hit.parentId)
        default:
            ItemDetailView(itemId: hit.parentId, apiClient: apiClient) {}
        }
    }

    private func performSearch() {
        let trimmed = viewModel.query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        selectedHit = nil

        #if DEBUG
        if let response = appState.uiTestUnifiedSearchResponse(query: trimmed) {
            viewModel.apply(response)
            return
        }
        #endif

        Task {
            await viewModel.search(apiClient: apiClient)
        }
    }

    private func clearSearch() {
        selectedHit = nil
        viewModel.clear()
    }

    private func isSelected(_ hit: UnifiedHit) -> Bool {
        selectedHit?.id == hit.id
    }

    private func resultsCountText(shown: Int, total: Int) -> String {
        let russian = OnboardingL10n.language(for: languageManager.current) == .russian
        if shown < total {
            return russian ? "Показано \(shown) из \(total)" : "Showing \(shown) of \(total)"
        }
        return russian ? "Найдено: \(total)" : "\(total) result\(total == 1 ? "" : "s")"
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct IOSUnifiedSearchDetailPlaceholder: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let hasResults: Bool
    let hasSearched: Bool

    var body: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 64, height: 64)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(spacing: Spacing.xxs) {
                Text(title)
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .multilineTextAlignment(.center)
                Text(subtitle)
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 380)
            }
        }
        .padding(Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("ios-unified-search-detail-placeholder")
    }

    private var title: String {
        if hasResults {
            return t("Select a Result", "Выберите результат")
        }
        return t("Search Your Second Brain", "Поиск по второму мозгу")
    }

    private var subtitle: String {
        if hasResults {
            return t(
                "Open a recording or material from the results on the left.",
                "Откройте запись или материал из результатов слева."
            )
        }
        if hasSearched {
            return t(
                "Try another search to find recordings and materials.",
                "Попробуйте другой запрос, чтобы найти записи и материалы."
            )
        }
        return t(
            "Search across recordings and captured materials, then keep results visible while reading.",
            "Ищите по записям и материалам, сохраняя результаты рядом с деталями."
        )
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct UnifiedSearchHitRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let hit: UnifiedHit

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: sourceIcon)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)

                Text(hit.title ?? t("Untitled", "Без названия"))
                    .font(Typography.headingMedium)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)

                Spacer()

                Text(localizedKind)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
                    .textCase(.uppercase)
            }

            Text(hit.snippet)
                .font(Typography.reading)
                .foregroundStyle(Palette.textSecondary)
                .lineSpacing(5)
                .lineLimit(3)
        }
        .padding(.vertical, Spacing.sm)
        .contentShape(Rectangle())
    }

    private var sourceIcon: String {
        switch hit.sourceKind {
        case "recording":
            return "waveform"
        case "chat":
            return "sparkles"
        default:
            return "doc.text"
        }
    }

    private var localizedKind: String {
        switch hit.kind.lowercased() {
        case "meeting":
            return t("Meeting", "Встреча")
        case "note":
            return t("Note", "Заметка")
        case "chat":
            return t("Chat", "Чат")
        case "article":
            return t("Article", "Статья")
        case "reflection":
            return t("Reflection", "Размышление")
        default:
            return hit.kind
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

@MainActor
final class IOSUnifiedSearchViewModel: ObservableObject {
    @Published var query = ""
    @Published private(set) var lastSubmittedQuery = ""
    @Published var results: [UnifiedHit] = []
    @Published var totalResults = 0
    @Published var isLoading = false
    @Published var error: String?
    @Published var hasSearched = false

    private var searchTask: Task<Void, Never>?

    deinit {
        searchTask?.cancel()
    }

    func apply(_ response: UnifiedSearchResponse) {
        lastSubmittedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        error = nil
        hasSearched = true
        isLoading = false
        results = response.results
        totalResults = response.total
    }

    func clear() {
        searchTask?.cancel()
        query = ""
        lastSubmittedQuery = ""
        results = []
        totalResults = 0
        error = nil
        hasSearched = false
        isLoading = false
    }

    func search(apiClient: APIClient) async {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

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
            results = response.results
            totalResults = response.total
        } catch {
            guard !Task.isCancelled else { return }
            self.error = error.userFacingMessage(context: .generic)
        }

        guard !Task.isCancelled else { return }
        isLoading = false
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
            ProgressView(t("Searching…", "Ищем…"))
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
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "waveform")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.typeColor(result.recordingType))

                Text(result.recordingTitle ?? t("Untitled", "Без названия"))
                    .font(Typography.headingMedium)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .layoutPriority(1)

                Spacer(minLength: Spacing.sm)

                Text(localizedKind)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
                    .textCase(.uppercase)
                    .lineLimit(1)
            }

            if let speaker = displaySpeaker {
                Text(speaker)
                    .font(Typography.label)
                    .foregroundStyle(Palette.accent)
                    .lineLimit(1)
            }

            Text(result.content)
                .font(Typography.reading)
                .foregroundStyle(Palette.textSecondary)
                .lineSpacing(5)
                .lineLimit(3)
        }
        .padding(.vertical, Spacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }

    private var localizedKind: String {
        switch result.recordingType {
        case .meeting:
            return t("Meeting", "Встреча")
        case .note:
            return t("Note", "Заметка")
        case .reflection:
            return t("Reflection", "Размышление")
        }
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

    /// Tracks the in-flight search so a mode change (or rapid re-submit) can
    /// cancel the previous request before starting a new one. Without this,
    /// two `@MainActor` searches interleave at every `await` and the slower
    /// one's results clobber the newer mode's. Mirrors
    /// `LibraryViewModel.processingRefreshTask`.
    private var searchTask: Task<Void, Never>?

    deinit {
        searchTask?.cancel()
    }

    /// Inject a deterministic response (DEBUG screenshot/UI-test fixture)
    /// without hitting the network. Mirrors `MacSearchViewModel`.
    func applySearchResponse(_ response: SearchResponse) {
        searchTask?.cancel()
        error = nil
        hasSearched = true
        isLoading = false
        results = response.results
        totalResults = response.total
    }

    func reset() {
        searchTask?.cancel()
        searchTask = nil
        results = []
        totalResults = 0
        hasSearched = false
        error = nil
        isLoading = false
    }

    func search(apiClient: APIClient) async {
        // Cancel any in-flight search before starting a new one so a mode
        // change or rapid re-submit can't let the older request clobber the
        // newer mode's results.
        searchTask?.cancel()
        let task = Task { [weak self] in
            guard let self else { return }
            await self.performSearch(apiClient: apiClient)
        }
        searchTask = task
        await task.value
    }

    private func performSearch(apiClient: APIClient) async {
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
            // A newer search (or reset) superseded this one while it was in
            // flight — drop these results so they can't clobber the newer mode.
            guard !Task.isCancelled else { return }
            results = response.results
            totalResults = response.total
        } catch {
            guard !Task.isCancelled else { return }
            results = []
            totalResults = 0
            self.error = error.userFacingMessage(context: .generic)
        }

        guard !Task.isCancelled else { return }
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
