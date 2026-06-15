import XCTest
import WaiComputerKit

@MainActor
final class MacContentFeedViewModelTests: XCTestCase {
    func testContentFeedDoesNotExposeCompareSelectionState() {
        let model = MacContentFeedViewModel(
            apiClient: APIClient(baseURL: URL(string: "https://example.test")!)
        )

        let propertyNames = Set(
            Mirror(reflecting: model).children.compactMap { child in
                child.label?.trimmingCharacters(in: CharacterSet(charactersIn: "_"))
            }
        )

        XCTAssertFalse(propertyNames.contains("compareSelection"))
        XCTAssertFalse(propertyNames.contains("activeComparisonId"))
        XCTAssertFalse(propertyNames.contains("isComparing"))
    }

    func testContentFeedViewDoesNotRenderSelectionControls() throws {
        let testFile = URL(fileURLWithPath: #filePath)
        let viewFile = testFile
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("WaiComputer/Features/Content/MacContentFeedView.swift")
        let source = try String(contentsOf: viewFile, encoding: .utf8)

        XCTAssertFalse(source.contains("List(selection:"))
        XCTAssertFalse(source.contains("Select to compare"))
        XCTAssertFalse(source.contains("Compare ("))
    }

    func testInboxViewUsesRecyclingListForFastScrollingRows() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        // Inbox rows live in a SwiftUI List (NSTableView-backed row reuse)
        // with a memoized display-row mapping. A custom NSScrollView
        // representable here re-entered NSHostingView layout on every wheel
        // frame on macOS 26 — the "inbox scroll freezes" bug — so its return
        // is treated as a regression, as is an unrecycled LazyVStack.
        XCTAssertTrue(source.contains("MacInboxRowsList("))
        XCTAssertTrue(source.contains("List {"))
        XCTAssertTrue(source.contains("displayCache.displayRows(for: rows, language: language)"))
        XCTAssertTrue(source.contains("ForEach(displayRows)"))
        XCTAssertFalse(source.contains("ForEach(Array(displayRows.enumerated())"))
        XCTAssertFalse(source.contains("NSViewRepresentable"))
        XCTAssertFalse(source.contains("LazyVStack(spacing: 0)"))
    }

    func testSearchResultsUseRecyclingListForFastScrollingRows() throws {
        let source = try macSource("WaiComputer/Features/Search/MacSearchView.swift")

        // Search can return long result sets. Keep results on an AppKit-backed
        // List instead of a ScrollView/LazyVStack so rows are measured and
        // recycled by the platform while scrolling.
        XCTAssertTrue(source.contains("List {"))
        XCTAssertTrue(source.contains(".searchResultListRow()"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"search-results-list\")"))
        XCTAssertFalse(source.contains("ScrollView {"))
        XCTAssertFalse(source.contains("LazyVStack"))
    }

    func testComparisonViewUsesRecyclingRowsForLargeMatrices() throws {
        let source = try macSource("WaiComputer/Features/Content/MacComparisonView.swift")

        // Comparison sets can grow as rows by columns. A Grid inside a two-axis
        // ScrollView eagerly builds every cell, which makes large comparisons
        // freeze during initial layout and scroll. Keep vertical rows recycled.
        XCTAssertTrue(source.contains("List {"))
        XCTAssertTrue(source.contains("comparisonHeaderRow("))
        XCTAssertTrue(source.contains("comparisonDataRow("))
        XCTAssertFalse(source.contains("ScrollView([.horizontal, .vertical])"))
        XCTAssertFalse(source.contains("Grid(alignment: .topLeading"))
        XCTAssertFalse(source.contains("GridRow"))
    }

    func testInboxViewDoesNotRenderStatusFilter() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertFalse(source.contains("Picker(t(\"Status\""))
        XCTAssertFalse(source.contains("setStatusFilter"))
    }

    func testInboxFileImporterStagesFileBeforeUpload() throws {
        let viewSource = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")
        let modelSource = try macSource("WaiComputer/Features/Inbox/MacInboxViewModel.swift")

        XCTAssertTrue(viewSource.contains("model.selectUploadFile(url)"))
        XCTAssertTrue(viewSource.contains("uploadPendingFile()"))
        XCTAssertTrue(viewSource.contains("private var canStartInboxUpload: Bool"))
        XCTAssertTrue(modelSource.contains("selectedUploadFile"))
        XCTAssertTrue(modelSource.contains("submitSelectedUploadFile()"))
        XCTAssertTrue(modelSource.contains("selectedUploadFileHasScopedAccess"))
        XCTAssertTrue(modelSource.contains("releaseSelectedUploadAccess()"))
        XCTAssertFalse(viewSource.contains("if let row = await model.uploadFile(url)"))
    }

    func testInboxCreatePaneShowsExplicitFileUploadState() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("MacInboxFileComposer("))
        XCTAssertTrue(source.contains("mac-inbox-selected-file"))
        XCTAssertTrue(source.contains("mac-inbox-upload-primary-button"))
        XCTAssertTrue(source.contains("mac-inbox-upload-choose-button"))
        XCTAssertTrue(source.contains("mac-inbox-upload-progress"))
        XCTAssertFalse(source.contains("Attach File"))
        XCTAssertFalse(source.contains("Прикрепить файл"))
        // "Загрузить файл" must appear exactly once in the composer: on the
        // mode card. The old pane repeated it as a panel title and again in
        // the primary button.
        XCTAssertFalse(source.contains("Upload File to Inbox"))
        XCTAssertFalse(source.contains("Загрузить файл в Инбокс"))
        XCTAssertFalse(source.contains("t(\"Upload a file\", \"Загрузить файл\")"))
        // The chooser is the drop zone itself — no second "Browse..." button
        // duplicating the primary action.
        XCTAssertFalse(source.contains("Browse..."))
        XCTAssertFalse(source.contains("Обзор..."))
    }

    func testInboxCreatePaneDefaultsToRecordAndFollowsScope() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("@State private var focusedCreateMode: InboxCreateMode = .record"))
        XCTAssertTrue(source.contains("Self.defaultCreateMode(for: initialSourceKind)"))
        XCTAssertTrue(source.contains("isActive: focusedCreateMode == .file"))
        XCTAssertTrue(source.contains("case .file:"))
        XCTAssertFalse(source.contains("activeCreateMode"))
        // The composer only offers actions matching the current source scope.
        XCTAssertTrue(source.contains("private var allowedCreateModes: [InboxCreateMode]"))
        XCTAssertTrue(source.contains("if allowedCreateModes.contains(.record)"))
        XCTAssertTrue(source.contains("if allowedCreateModes.contains(.ask)"))
    }

    func testInboxRecordComposerExposesStartRecordingIdentifier() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("primaryAccessibilityIdentifier: \"start-recording-button\""))
        XCTAssertTrue(source.contains("accessibilityIdentifier(identifier)"))
    }

    func testLiveRecordingTranscriptPublishesOnlyOneDisplayInvalidationPerEvent() throws {
        let source = try macSource("WaiComputer/Features/Recording/MacRecordingViewModel.swift")

        // Live transcription events arrive several times per second. The model
        // must not publish a third, full-string currentTranscript copy on every
        // event, and it must batch committed/interim display updates behind one
        // explicit objectWillChange send.
        XCTAssertFalse(source.contains("@Published var currentTranscript"))
        XCTAssertTrue(source.contains("var currentTranscript: String {"))
        XCTAssertTrue(source.contains("private(set) var committedTranscript = \"\""))
        XCTAssertTrue(source.contains("private(set) var interimTranscript = \"\""))
        XCTAssertTrue(source.contains("objectWillChange.send()"))
        XCTAssertTrue(source.contains("setLiveTranscript(committed: committed, interim: interim)"))
        XCTAssertFalse(source.contains("currentTranscript = combinedTranscript(committed: committed, interim: interim)"))
    }

    func testLiveRecordingViewAvoidsFullTranscriptObservationForScrollFollow() throws {
        let source = try macSource("WaiComputer/Features/Recording/LiveRecordingView.swift")

        // The live tail can grow very large. Auto-follow should be driven by a
        // cheap layout token, not by reading the full combined transcript string
        // from the view on every interim tick.
        XCTAssertTrue(source.contains("LiveTranscriptScrollToken("))
        XCTAssertTrue(source.contains("private var transcriptHasContent: Bool"))
        XCTAssertTrue(source.contains(".onChangeCompat(of: transcriptScrollToken)"))
        XCTAssertFalse(source.contains("recordingVM.currentTranscript"))
    }

    func testLiveRecordingViewUsesRecyclingRowsForLongTranscriptDisplay() throws {
        let viewSource = try macSource("WaiComputer/Features/Recording/LiveRecordingView.swift")
        let modelSource = try macSource("WaiComputer/Features/Recording/MacRecordingViewModel.swift")

        // Long live recordings must not keep laying out one ever-growing Text.
        // The view reads pre-split committed chunks from the model and renders
        // them as platform-recycled rows.
        XCTAssertTrue(modelSource.contains("private(set) var committedTranscriptChunks: [LiveTranscriptDisplayChunk] = []"))
        XCTAssertTrue(modelSource.contains("committedTranscriptChunks = Self.liveTranscriptDisplayChunks(from: committed)"))
        XCTAssertTrue(viewSource.contains("List {"))
        XCTAssertTrue(viewSource.contains("ForEach(recordingVM.committedTranscriptChunks)"))
        XCTAssertTrue(viewSource.contains(".liveTranscriptListRow()"))
        XCTAssertFalse(viewSource.contains("Text(recordingVM.committedTranscript)"))
        XCTAssertFalse(viewSource.contains("LazyVStack"))
    }

    func testInboxSourceFilterPutsAllLastAndShellDefaultsInboxToRecordings() throws {
        let inboxSource = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")
        let shellSource = try macSource("WaiComputer/App/MacContentView.swift")

        // Все is the last segment, Записи the first.
        let recordingsTag = inboxSource.range(of: "tag(Optional.some(InboxSourceKind.recording))")
        let allTag = inboxSource.range(of: "tag(Optional<InboxSourceKind>.none)")
        let recordingsIndex = try XCTUnwrap(recordingsTag).lowerBound
        let allIndex = try XCTUnwrap(allTag).lowerBound
        XCTAssertLessThan(recordingsIndex, allIndex)
        // Opening the Inbox section starts scoped to recordings.
        XCTAssertTrue(shellSource.contains("case .inbox, .allRecordings:\n            return .recording"))
    }

    func testCommandNOpensInboxCreatePaneInsteadOfStartingRecording() throws {
        let appSource = try macSource("WaiComputer/App/WaiComputerMacApp.swift")
        let shellSource = try macSource("WaiComputer/App/MacContentView.swift")
        let inboxSource = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(appSource.contains("Button(t(\"New Inbox Item\", \"Новый объект в Инбоксе\"))"))
        XCTAssertTrue(appSource.contains(".keyboardShortcut(\"n\", modifiers: .command)"))
        XCTAssertTrue(appSource.contains("postInboxCommand(.showCreatePane)"))
        XCTAssertTrue(shellSource.contains("routeInboxCommand(command)"))
        XCTAssertTrue(inboxSource.contains("case .showCreatePane:"))
        XCTAssertFalse(appSource.contains(".keyboardShortcut(\"n\", modifiers: .command)\n                .disabled(isRecordingActivityVisible || !appState.isAuthenticated)\n\n                Divider()\n\n                Button(t(\"Import Audio File\""))
        XCTAssertFalse(appSource.contains("Task { await appState.startRecording(type: .meeting, inputSource: .dual) }\n                }\n                .keyboardShortcut(\"n\", modifiers: .command)"))
    }

    func testInboxCommandMenuCoversAllCreateActionsWithShortcuts() throws {
        let source = try macSource("WaiComputer/App/WaiComputerMacApp.swift")

        XCTAssertTrue(source.contains("Button(t(\"Record Now\", \"Записать сейчас\"))"))
        XCTAssertTrue(source.contains("postInboxCommand(.recordNow)"))
        XCTAssertTrue(source.contains(".keyboardShortcut(\"r\", modifiers: [.command, .shift])"))
        XCTAssertTrue(source.contains("Button(t(\"Upload File\", \"Загрузить файл\"))"))
        XCTAssertTrue(source.contains("postInboxCommand(.uploadFile)"))
        XCTAssertTrue(source.contains(".keyboardShortcut(\"u\", modifiers: [.command, .option])"))
        XCTAssertTrue(source.contains("Button(t(\"Paste Link or Text\", \"Вставить ссылку или текст\"))"))
        XCTAssertTrue(source.contains("postInboxCommand(.pasteLinkOrText)"))
        XCTAssertTrue(source.contains(".keyboardShortcut(\"v\", modifiers: [.command, .option])"))
        XCTAssertTrue(source.contains("Button(\"Wai\")"))
        XCTAssertTrue(source.contains("postInboxCommand(.askWai)"))
        XCTAssertTrue(source.contains(".keyboardShortcut(\"a\", modifiers: [.command, .option])"))
    }

    func testNavigationShortcutsFollowSidebarOrder() throws {
        let source = try macSource("WaiComputer/App/WaiComputerMacApp.swift")

        XCTAssertBefore("object: \"inbox\"", ".keyboardShortcut(\"1\", modifiers: .command)", in: source)
        XCTAssertBefore("object: \"trash\"", ".keyboardShortcut(\"2\", modifiers: .command)", in: source)
        XCTAssertBefore("object: \"history\"", ".keyboardShortcut(\"3\", modifiers: .command)", in: source)
        XCTAssertBefore("object: \"dictionary\"", ".keyboardShortcut(\"4\", modifiers: .command)", in: source)
        XCTAssertTrue(source.contains("CommandMenu(t(\"Navigate\", \"Переход\"))"))
        XCTAssertTrue(source.contains("Button(t(\"New Folder\", \"Новая папка\"))"))
        XCTAssertTrue(source.contains(".keyboardShortcut(\"n\", modifiers: [.command, .shift])"))
    }

    func testInboxRowsKeepFlatChromeFreeStyling() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        // The List keeps the table's flat look: plain style, no system
        // background, edge-to-edge rows without separators.
        XCTAssertTrue(source.contains(".listStyle(.plain)"))
        XCTAssertTrue(source.contains(".scrollContentBackground(.hidden)"))
        XCTAssertTrue(source.contains(".listRowSeparator(.hidden)"))
        XCTAssertTrue(source.contains(".listRowInsets(EdgeInsets())"))
    }

    func testInboxUsesAutomaticPaginationInsteadOfManualLoadMoreFooter() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        // Pagination fires when a row near the end appears (the lookahead
        // mirrors the old 256px-before-bottom threshold) — never via a
        // user-facing "Load more" button.
        XCTAssertTrue(source.contains("onLoadMore:"))
        XCTAssertTrue(source.contains("loadMoreLookahead"))
        XCTAssertTrue(source.contains("canLoadMore, !isLoadingMore"))
        XCTAssertFalse(source.contains("Load More"))
        XCTAssertFalse(source.contains("Показать ещё"))
    }

    func testInboxLayoutPinsPanesAndMakesCreatePaneScrollable() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains(".frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)"))
        XCTAssertTrue(source.contains("private var createPane: some View {\n        GeometryReader"))
        XCTAssertTrue(source.contains("ScrollView {"))
    }

    func testInboxChatDetailUsesFocusedCompanionWithoutSwitcher() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("showsConversationSwitcher: false"))
    }

    func testInboxChatDetailPassesFolderContextToFocusedCompanion() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("viewingFolderId: folderId"))
    }

    func testCompanionViewForwardsViewingContextToStreamRequest() throws {
        let source = try sharedSource("Sources/WaiComputerKit/Views/CompanionView.swift")

        XCTAssertTrue(source.contains("private let viewingRecordingId: String?"))
        XCTAssertTrue(source.contains("private let viewingFolderId: String?"))
        XCTAssertTrue(source.contains("private let onTurnCompleted: ((CompanionTurnCompletion) -> Void)?"))
        XCTAssertTrue(source.contains("viewingRecordingId: viewingRecordingId"))
        XCTAssertTrue(source.contains("viewingFolderId: viewingFolderId"))
        XCTAssertTrue(source.contains("onTurnCompleted?(CompanionTurnCompletion("))
    }

    func testCompanionViewReusesRelativeDateFormattersForScrollingChatRows() throws {
        let source = try sharedSource("Sources/WaiComputerKit/Views/CompanionView.swift")

        XCTAssertTrue(source.contains("CompanionRelativeDateFormatterCache.string("))
        XCTAssertTrue(source.contains("private enum CompanionRelativeDateFormatterCache"))
        XCTAssertTrue(source.contains("private static var formatters: [String: RelativeDateTimeFormatter]"))
        XCTAssertFalse(source.contains("let formatter = RelativeDateTimeFormatter()"))
    }

    func testCompanionMessageStreamUsesRecyclingRowsOnMac() throws {
        let source = try sharedSource("Sources/WaiComputerKit/Views/CompanionView.swift")

        // Long Wai threads can contain many rich assistant turns. The macOS
        // message stream should use List row reuse instead of keeping the full
        // conversation in a LazyVStack while scrolling.
        XCTAssertTrue(source.contains("private var macMessageList: some View"))
        XCTAssertTrue(source.contains("private var messageRows: some View"))
        XCTAssertTrue(source.contains("List {"))
        XCTAssertTrue(source.contains("messageRows"))
        XCTAssertTrue(source.contains(".companionMessageListRow()"))
        XCTAssertFalse(source.contains("ScrollView {\n                    LazyVStack(alignment: .leading, spacing: 0) {\n                        if messages.isEmpty"))
    }

    func testInboxFocusedCompanionNotifiesWhenTurnCompletes() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("onTurnCompleted: { completion in"))
        XCTAssertTrue(source.contains("MacWaiTaskNotificationCenter.shared.notifyTaskFinished("))
        XCTAssertTrue(source.contains("body: completion.preview ?? OnboardingL10n.text("))
        XCTAssertTrue(source.contains("\"Your Wai task is ready.\", \"Задача Wai готова.\", language: language"))
    }

    func testMacWaiTaskNotificationCenterRequestsPermissionInForegroundOnly() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacWaiTaskNotificationCenter.swift")

        XCTAssertTrue(source.contains("import UserNotifications"))
        // HIG: the system permission dialog may only appear in context — a Wai
        // turn finishing while the app is frontmost. Background finishes are
        // delivery-only and never trigger requestAuthorization.
        XCTAssertTrue(source.contains("guard !application.isActive else {\n            requestAuthorizationIfNeeded()\n            return\n        }"))
        XCTAssertTrue(source.contains("guard settings.authorizationStatus == .notDetermined else { return }"))
        XCTAssertTrue(source.contains("requestAuthorization(options: [.alert, .sound])"))
        XCTAssertTrue(source.contains("UNNotificationRequest("))
        XCTAssertFalse(source.contains("try?"))
    }

    func testMacAppConfiguresTaskNotificationCenterAtLaunch() throws {
        let source = try macSource("WaiComputer/App/WaiComputerMacApp.swift")

        XCTAssertTrue(source.contains("MacWaiTaskNotificationCenter.shared.configure()"))
    }

    func testMacNotificationTapRoutesFinishedChatToInbox() throws {
        let appSource = try macSource("WaiComputer/App/WaiComputerMacApp.swift")
        let contentSource = try macSource("WaiComputer/App/MacContentView.swift")
        let notificationSource = try macSource("WaiComputer/Features/Inbox/MacWaiTaskNotificationCenter.swift")

        XCTAssertTrue(appSource.contains("static let macOpenInboxChat = Notification.Name(\"macOpenInboxChat\")"))
        XCTAssertTrue(notificationSource.contains("NotificationCenter.default.post(name: .macOpenInboxChat, object: chatId)"))
        XCTAssertTrue(contentSource.contains("NotificationCenter.default.publisher(for: .macOpenInboxChat)"))
        XCTAssertTrue(contentSource.contains("pendingInboxDetail = InboxDetailRef(kind: .chat, id: chatId)"))
        XCTAssertTrue(contentSource.contains("selectedSection = .inbox"))
    }

    func testInboxPresentsWaiChatAsAgentThread() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("New Wai Session"))
        XCTAssertTrue(source.contains("Give Wai a task"))
        XCTAssertFalse(source.contains("Ask Wai"))
        XCTAssertFalse(source.contains("New Wai Chat"))
        XCTAssertFalse(source.contains("Wai Chat"))
    }

    func testInboxIsTheOnlyWaiAgentSurface() throws {
        let inboxSource = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")
        let shellSource = try macSource("WaiComputer/App/MacContentView.swift")

        XCTAssertTrue(inboxSource.contains("case .chat:"))
        XCTAssertTrue(inboxSource.contains("CompanionView("))
        XCTAssertTrue(inboxSource.contains("New Wai Session"))
        XCTAssertTrue(inboxSource.contains("Give Wai a task"))
        XCTAssertFalse(inboxSource.contains("Ask Wai"))
        XCTAssertTrue(shellSource.contains(#"case "agents": selectedSection = .inbox"#))
        XCTAssertFalse(shellSource.contains("case agents"))
        XCTAssertFalse(shellSource.contains("MacAgentsView("))
        XCTAssertFalse(shellSource.contains(#"sidebarRow(t("Agents""#))
    }

    func testInboxViewModelClearsStaleErrorAfterSuccessfulReload() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxViewModel.swift")

        XCTAssertTrue(source.contains("errorMessage = nil\n            rows = response.rows"))
        XCTAssertTrue(source.contains("errorMessage = nil\n            rows.append(contentsOf: response.rows)"))
    }

    func testCompanionViewCanHideChatSwitcherAndDoesNotShowChatCounts() throws {
        let source = try sharedSource("Sources/WaiComputerKit/Views/CompanionView.swift")

        XCTAssertTrue(source.contains("showsConversationSwitcher: Bool = true"))
        XCTAssertTrue(source.contains("if showsConversationSwitcher {"))
        XCTAssertFalse(source.contains("chatsCountLabel"))
        XCTAssertFalse(source.contains("Чаты: \\("))
        XCTAssertFalse(source.contains("Chats (\\("))
    }

    func testMacDateFormattingCachesFormattersForLargeLists() throws {
        let source = try macSource("WaiComputer/Core/DesignSystem.swift")

        XCTAssertTrue(source.contains("formatterCache"))
        XCTAssertTrue(source.contains("formatterCacheLock"))
    }

    func testDictationHistoryUsesRecyclingListAndMemoizedGrouping() throws {
        let source = try macSource("WaiComputer/Features/Dictation/DictationHistoryView.swift")

        XCTAssertTrue(source.contains("@State private var displayCache = DictationHistoryDisplayCache()"))
        XCTAssertTrue(source.contains("displayCache.groups("))
        XCTAssertTrue(source.contains("List {"))
        XCTAssertFalse(source.contains("ScrollView {"))
        XCTAssertFalse(source.contains("LazyVStack(spacing: 0)"))
    }

    func testDictationDictionaryUsesRecyclingListAndMemoizedFiltering() throws {
        let source = try macSource("WaiComputer/Features/Dictation/DictationDictionaryView.swift")

        XCTAssertTrue(source.contains("@State private var displayCache = DictationDictionaryDisplayCache()"))
        XCTAssertTrue(source.contains("displayCache.words("))
        XCTAssertTrue(source.contains("List {"))
        XCTAssertTrue(source.contains("ForEach(visibleWords)"))
        XCTAssertFalse(source.contains("private var filteredWords"))
        XCTAssertFalse(source.contains("ForEach(filteredWords)"))
    }

    func testPeekabooSmokeLaunchesFixturesWithExplicitOpenEnvironment() throws {
        let source = try repoSource("scripts/macos-peekaboo-smoke.sh")

        XCTAssertTrue(source.contains("--env WAI_ENABLE_UI_TEST_MODE=1"))
        XCTAssertTrue(source.contains("--env UITEST_SCENARIO=\"$scenario\""))
        XCTAssertTrue(source.contains("--env WAI_DISABLE_STORED_SESSION_RESTORE=1"))
        XCTAssertTrue(source.contains("--env WAI_SKIP_ONBOARDING=1"))
        XCTAssertTrue(source.contains("--env WAI_MOCK_DICTATION_PERMISSIONS=\"$permission_mock\""))
        XCTAssertBefore("--env WAI_ENABLE_UI_TEST_MODE=1", "--args -ApplePersistenceIgnoreState YES", in: source)
        XCTAssertTrue(source.contains("wait_for_ui_text main-ready \"Inbox\""))
        XCTAssertFalse(source.contains("wait_for_ui_text main-ready \"All Recordings\""))
        XCTAssertFalse(source.contains("\"import-audio-button\" || die \"Import button missing\""))
    }

    func testPeekabooSmokeRefreshesWindowBeforeCaptureAndClick() throws {
        let source = try repoSource("scripts/macos-peekaboo-smoke.sh")

        // SwiftUI can recreate the main NSWindow during recording transitions.
        // The smoke gate must refresh the target window instead of reusing a
        // stale id through the whole scenario.
        XCTAssertTrue(source.contains("open -g -n"))
        XCTAssertTrue(source.contains("WINDOW_X=\"${WAICOMPUTER_PEEKABOO_WINDOW_X:-32000}\""))
        XCTAssertTrue(source.contains("refresh_target_window_id \"$name\""))
        XCTAssertTrue(source.contains("refresh_target_window_id \"$name-retry\""))
        XCTAssertTrue(source.contains("refresh_target_window_for_interaction \"$identifier\""))
        XCTAssertTrue(source.contains("refresh_target_window_for_interaction \"$name\""))
        XCTAssertTrue(source.contains("refresh_target_app_ref()"))
        XCTAssertTrue(source.contains("TARGET_PID=\"$pid\""))
        XCTAssertTrue(source.contains("if ! peekaboo list windows --pid \"$TARGET_PID\""))
        XCTAssertTrue(source.contains("peekaboo perform-action --snapshot \"$fresh_snapshot\" --on \"$element_id\" --action AXPress"))
        XCTAssertTrue(source.contains("peekaboo set-value \"$value\" --snapshot \"$fresh_snapshot\" --on \"$element_id\""))
        XCTAssertTrue(source.contains("set_identifier_label_role_value search-bar \"Search recordings...\" \"text field\" search search-field"))
        XCTAssertTrue(source.contains("click_identifier_label_role search-bar Search button search-submit"))
        XCTAssertTrue(source.contains("element_id_by_identifier_label_role \"$json_path\" \"$identifier\" \"$label\" \"$role\""))
        XCTAssertTrue(source.contains("set_target_window_bounds()"))
        XCTAssertTrue(source.contains("refresh_target_window_id \"$name-bounds\""))
        XCTAssertTrue(source.contains("refresh_target_window_id \"$name-bounds-retry\""))
        XCTAssertTrue(source.contains("--x \"$WINDOW_X\""))
        XCTAssertTrue(source.contains("if ! peekaboo window set-bounds"))
        XCTAssertFalse(source.contains("peekaboo app switch"))
        XCTAssertFalse(source.contains("peekaboo window focus"))
        XCTAssertFalse(source.contains("peekaboo click"))
        XCTAssertFalse(source.contains("peekaboo type"))
        XCTAssertFalse(source.contains("peekaboo press"))
        XCTAssertFalse(source.contains("--bring-to-current-space"))
    }

    func testMacXCUITestsRequireExplicitForegroundOptIn() throws {
        let policy = try repoSource("macos/WaiComputer/WaiComputerUITests/WaiComputerUITestForegroundPolicy.swift")
        XCTAssertTrue(policy.contains("WAI_ALLOW_FOREGROUND_XCUITESTS"))
        XCTAssertTrue(policy.contains("scripts/macos-peekaboo-smoke.sh"))
        XCTAssertTrue(policy.contains("XCTSkip"))

        let uiTestsURL = try repoURL("macos/WaiComputer/WaiComputerUITests")
        let sources = try FileManager.default.contentsOfDirectory(
            at: uiTestsURL,
            includingPropertiesForKeys: nil
        )
        .filter { $0.pathExtension == "swift" }
        .filter {
            ![
                "WaiComputerUITestAppLauncher.swift",
                "WaiComputerUITestForegroundPolicy.swift",
            ].contains($0.lastPathComponent)
        }

        XCTAssertFalse(sources.isEmpty)
        for sourceURL in sources {
            let source = try String(contentsOf: sourceURL, encoding: .utf8)
            guard source.contains(": XCTestCase") else { continue }
            XCTAssertTrue(
                source.contains("try requireForegroundXCUITestOptIn()"),
                "\(sourceURL.lastPathComponent) can foreground WaiComputer without explicit opt-in"
            )
        }
    }

    func testPeekabooSmokePassesOffscreenWindowBoundsAtLaunch() throws {
        let script = try repoSource("scripts/macos-peekaboo-smoke.sh")
        let appSource = try macSource("WaiComputer/App/WaiComputerMacApp.swift")

        XCTAssertTrue(script.contains("--env WAICOMPUTER_TEST_WINDOW_X=\"$WINDOW_X\""))
        XCTAssertTrue(script.contains("--env WAICOMPUTER_TEST_WINDOW_Y=\"$WINDOW_Y\""))
        XCTAssertTrue(script.contains("--env WAICOMPUTER_TEST_WINDOW_WIDTH=\"$WINDOW_WIDTH\""))
        XCTAssertTrue(script.contains("--env WAICOMPUTER_TEST_WINDOW_HEIGHT=\"$WINDOW_HEIGHT\""))
        XCTAssertTrue(script.contains("set_launch_env WAICOMPUTER_TEST_WINDOW_X \"$WINDOW_X\""))
        XCTAssertTrue(script.contains("set_launch_env WAICOMPUTER_TEST_WINDOW_Y \"$WINDOW_Y\""))
        XCTAssertTrue(script.contains("set_launch_env WAICOMPUTER_TEST_WINDOW_WIDTH \"$WINDOW_WIDTH\""))
        XCTAssertTrue(script.contains("set_launch_env WAICOMPUTER_TEST_WINDOW_HEIGHT \"$WINDOW_HEIGHT\""))

        XCTAssertTrue(appSource.contains("placeMainWindowForUITestingIfNeeded()"))
        XCTAssertTrue(appSource.contains("WAICOMPUTER_TEST_WINDOW_X"))
        XCTAssertTrue(appSource.contains("WAICOMPUTER_TEST_WINDOW_Y"))
        XCTAssertTrue(appSource.contains("WAICOMPUTER_TEST_WINDOW_WIDTH"))
        XCTAssertTrue(appSource.contains("WAICOMPUTER_TEST_WINDOW_HEIGHT"))
        XCTAssertBefore("placeMainWindowForUITestingIfNeeded()", "centerMainWindowIfNeeded()", in: appSource)
    }

    func testRecordingDetailShowsSummaryBeforeTranscriptWithoutTabs() throws {
        let source = try macSource("WaiComputer/Features/Library/MacRecordingDetailView.swift")

        XCTAssertFalse(source.contains("WaiTabBar("))
        // The transcript is flattened into the outer LazyVStack for scroll perf
        // (1.0.39); its header is the stable marker that follows the summary.
        XCTAssertBefore("summarySection(detail)", "transcriptHeader(detail)", in: source)
    }

    func testRecordingDetailMemoizesSummaryDisplayRowsForFastInvalidations() throws {
        let source = try macSource("WaiComputer/Features/Library/MacRecordingDetailView.swift")

        // Summary/detail rows can sit above long transcripts. Keep filtering,
        // copy-text joining, and row identity construction out of ordinary
        // body invalidations so scroll and header state changes do not rebuild
        // the whole summary display tree.
        XCTAssertTrue(source.contains("@State private var summaryDisplayCache = MacRecordingSummaryDisplayCache()"))
        XCTAssertTrue(source.contains("summaryDisplayCache.display("))
        XCTAssertTrue(source.contains("MacRecordingSummaryDisplay"))
        XCTAssertTrue(source.contains("ForEach(display.keyPoints)"))
        XCTAssertTrue(source.contains("ForEach(display.actionItems)"))
        XCTAssertTrue(source.contains("summaryTagSection(title: t(\"Topics\", \"Темы\"), rows: display.topics)"))
        XCTAssertTrue(source.contains("summaryTagSection(title: t(\"People\", \"Люди\"), rows: display.people)"))
        XCTAssertTrue(source.contains("ForEach(rows)"))
        XCTAssertFalse(source.contains("private func visibleActionItems"))
        XCTAssertFalse(source.contains("private func fullSummaryText"))
        XCTAssertFalse(source.contains("ForEach(points, id: \\.self)"))
        XCTAssertFalse(source.contains("ForEach(values, id: \\.self)"))
    }

    func testRecordingDetailExposesSummaryAudioInHeaderActions() throws {
        let source = try macSource("WaiComputer/Features/Library/MacRecordingDetailView.swift")

        XCTAssertTrue(source.contains("headerSummaryAudioButton(detail, showsLabel: showsLabels)"))
        XCTAssertTrue(source.contains("recording-detail-summary-audio-create-button"))
        XCTAssertTrue(source.contains("recording-detail-summary-audio-play-button"))
        XCTAssertBefore("headerSummaryAudioButton(detail, showsLabel: showsLabels)", "moveToFolderMenu(detail", in: source)
    }

    func testRecordingDetailViewModelDoesNotDefaultToTranscriptTab() throws {
        let source = try macSource("WaiComputer/Features/Library/MacRecordingDetailViewModel.swift")

        XCTAssertFalse(source.contains("selectedTab: Tab = .transcript"))
        XCTAssertFalse(source.contains("enum Tab"))
    }

    func testItemDetailShowsSummaryBeforeOriginalMaterial() throws {
        let source = try macSource("WaiComputer/Features/Content/MacItemDetailView.swift")

        XCTAssertBefore("summarySection", "originalMaterialSection", in: source)
        XCTAssertTrue(source.contains("Original Material"))
        XCTAssertTrue(source.contains("item.body"))
    }

    func testItemDetailUsesRecyclingListAndChunksOriginalBodyForFastScrolling() throws {
        let source = try macSource("WaiComputer/Features/Content/MacItemDetailView.swift")

        // Large pasted notes/articles used to render as one huge selectable Text
        // inside a ScrollView, forcing SwiftUI to lay out the whole source body
        // while scrolling. Keep item details on List and split original text
        // into reusable rows.
        XCTAssertTrue(source.contains("List {"))
        XCTAssertTrue(source.contains("OriginalMaterialChunk"))
        XCTAssertTrue(source.contains("originalMaterialChunks"))
        XCTAssertTrue(source.contains("ItemKeyPointRow"))
        XCTAssertTrue(source.contains("content.keyPointRows"))
        XCTAssertTrue(source.contains("ForEach(content.originalBodyChunks)"))
        XCTAssertTrue(source.contains("ForEach(content.keyPointRows)"))
        XCTAssertTrue(source.contains(".itemDetailListRow()"))
        XCTAssertFalse(source.contains("ScrollView {"))
        XCTAssertFalse(source.contains("Text(body)"))
        XCTAssertFalse(source.contains("ForEach(Array(keyPoints.enumerated())"))
    }

    func testStandaloneTranscriptViewUsesRecyclingListAndCachedTurns() throws {
        let source = try macSource("WaiComputer/Features/Library/MacTranscriptView.swift")

        // Keep the standalone transcript renderer aligned with the recording
        // detail path: merged transcript turns are cached, and rows live in a
        // List instead of a ScrollView/LazyVStack.
        XCTAssertTrue(source.contains("@State private var displayCache = MacTranscriptDisplayCache()"))
        XCTAssertTrue(source.contains("let turns = displayCache.turns("))
        XCTAssertTrue(source.contains("List {"))
        XCTAssertTrue(source.contains("ForEach(turns)"))
        XCTAssertFalse(source.contains("ScrollView {"))
        XCTAssertFalse(source.contains("LazyVStack"))
        XCTAssertFalse(source.contains("ForEach(TranscriptRendering.mergeTurns"))
    }

    func testSpeakerPickerUsesRecyclingRowsAndCachedFiltering() throws {
        let source = try macSource("WaiComputer/Features/Library/SpeakerChipView.swift")

        // Speaker assignment opens from transcript rows. The people directory can
        // grow over time, so the popover must not filter during every render or
        // scroll an unrecycled LazyVStack.
        XCTAssertTrue(source.contains("@State private var visiblePeople: [Person] = []"))
        XCTAssertTrue(source.contains("ForEach(visiblePeople)"))
        XCTAssertTrue(source.contains(".speakerPickerListRow()"))
        XCTAssertTrue(source.contains("private func refreshVisiblePeople()"))
        XCTAssertTrue(source.contains(".onChangeCompat(of: filter)"))
        XCTAssertFalse(source.contains("ForEach(filteredPeople)"))
        XCTAssertFalse(source.contains("private var filteredPeople: [Person]"))
        XCTAssertFalse(source.contains("ScrollView {\n                LazyVStack"))
        XCTAssertFalse(source.contains("LazyVStack(alignment: .leading, spacing: 2)"))
    }

    func testRecordingListContextMenuAvoidsFullListFilterForSingleRowActions() throws {
        let source = try macSource("WaiComputer/Features/Library/RecordingListView.swift")

        // Opening a row context menu should not eagerly filter every displayed
        // recording just to decide whether "Remove from Folder" is available.
        // Single-row menus are the common path and can answer from the row model.
        XCTAssertTrue(source.contains("private func canRemoveFromFolder("))
        XCTAssertTrue(source.contains("contextSelection.count == 1"))
        XCTAssertTrue(source.contains("return recording.folderId != nil"))
        XCTAssertFalse(source.contains("let contextRecordings = recordings.filter"))
        XCTAssertFalse(source.contains("contextRecordings.contains"))
    }

    func testLibraryRecordingListUsesMemoizedDisplayInput() throws {
        let source = try macSource("WaiComputer/App/MacContentView.swift")

        // The legacy recordings column is still a large scroll surface. Keep
        // folder/trash filtering out of ordinary view invalidations so shell
        // state changes do not hand a freshly-filtered array to the List.
        XCTAssertTrue(source.contains("@State private var recordingDisplayCache = MacRecordingDisplayCache()"))
        XCTAssertTrue(source.contains("recordingDisplayCache.recordings("))
        XCTAssertTrue(source.contains("private final class MacRecordingDisplayCache"))
        XCTAssertFalse(source.contains("private var displayedRecordings: [Recording]"))
        XCTAssertFalse(source.contains("let displayed = displayedRecordings"))
        XCTAssertFalse(source.contains("libraryViewModel.filteredRecordings("))
    }

    private func macSource(_ relativePath: String) throws -> String {
        let file = try repoRoot().appendingPathComponent("macos/WaiComputer").appendingPathComponent(relativePath)
        return try String(contentsOf: file, encoding: .utf8)
    }

    private func repoSource(_ relativePath: String) throws -> String {
        try String(contentsOf: try repoURL(relativePath), encoding: .utf8)
    }

    private func repoURL(_ relativePath: String) throws -> URL {
        try repoRoot()
            .appendingPathComponent(relativePath)
    }

    private func sharedSource(_ relativePath: String) throws -> String {
        let file = try repoRoot()
            .appendingPathComponent("shared/WaiComputerKit")
            .appendingPathComponent(relativePath)
        return try String(contentsOf: file, encoding: .utf8)
    }

    private func repoRoot() throws -> URL {
        let candidates = [
            URL(fileURLWithPath: #filePath),
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath),
        ]

        for candidate in candidates {
            var directory = candidate.hasDirectoryPath ? candidate : candidate.deletingLastPathComponent()
            while directory.path != directory.deletingLastPathComponent().path {
                let marker = directory.appendingPathComponent("scripts/macos-peekaboo-smoke.sh")
                if FileManager.default.fileExists(atPath: marker.path) {
                    return directory
                }
                directory.deleteLastPathComponent()
            }
        }

        throw XCTSkip("Unable to locate wai-computer repo root from test runtime")
    }

    private func XCTAssertBefore(
        _ earlier: String,
        _ later: String,
        in source: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        guard let earlierIndex = source.range(of: earlier)?.lowerBound else {
            XCTFail("Missing \(earlier)", file: file, line: line)
            return
        }
        guard let laterIndex = source.range(of: later)?.lowerBound else {
            XCTFail("Missing \(later)", file: file, line: line)
            return
        }
        XCTAssertLessThan(earlierIndex, laterIndex, file: file, line: line)
    }
}
