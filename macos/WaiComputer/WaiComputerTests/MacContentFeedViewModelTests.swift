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
        XCTAssertFalse(source.contains("NSViewRepresentable"))
        XCTAssertFalse(source.contains("LazyVStack(spacing: 0)"))
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
        XCTAssertTrue(source.contains("focus_target_window()"))
        XCTAssertTrue(source.contains("refresh_target_window_id \"$name\""))
        XCTAssertTrue(source.contains("refresh_target_window_id \"$name-retry\""))
        XCTAssertTrue(source.contains("focus_target_window \"$identifier\""))
        XCTAssertTrue(source.contains("focus_target_window \"$name\""))
        XCTAssertTrue(source.contains("--no-auto-focus"))
        XCTAssertTrue(source.contains("refresh_target_app_ref()"))
        XCTAssertTrue(source.contains("TARGET_APP_REF=\"PID:$pid\""))
        XCTAssertTrue(source.contains("if ! peekaboo list windows --app \"$TARGET_APP_REF\""))
        XCTAssertTrue(source.contains("set_target_window_bounds()"))
        XCTAssertTrue(source.contains("refresh_target_window_id \"$name-bounds\""))
        XCTAssertTrue(source.contains("refresh_target_window_id \"$name-bounds-retry\""))
        XCTAssertTrue(source.contains("if ! peekaboo window set-bounds"))
        XCTAssertFalse(source.contains("peekaboo window focus --window-id \"$TARGET_WINDOW_ID\" --bring-to-current-space --json > \"$RUN_DIR/focus-before-$identifier.json\" || true"))
    }

    func testRecordingDetailShowsSummaryBeforeTranscriptWithoutTabs() throws {
        let source = try macSource("WaiComputer/Features/Library/MacRecordingDetailView.swift")

        XCTAssertFalse(source.contains("WaiTabBar("))
        // The transcript is flattened into the outer LazyVStack for scroll perf
        // (1.0.39); its header is the stable marker that follows the summary.
        XCTAssertBefore("summarySection(detail)", "transcriptHeader(detail)", in: source)
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

    private func macSource(_ relativePath: String) throws -> String {
        let testFile = URL(fileURLWithPath: #filePath)
        let file = testFile
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(relativePath)
        return try String(contentsOf: file, encoding: .utf8)
    }

    private func repoSource(_ relativePath: String) throws -> String {
        let testFile = URL(fileURLWithPath: #filePath)
        let file = testFile
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(relativePath)
        return try String(contentsOf: file, encoding: .utf8)
    }

    private func sharedSource(_ relativePath: String) throws -> String {
        let testFile = URL(fileURLWithPath: #filePath)
        let file = testFile
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("shared/WaiComputerKit")
            .appendingPathComponent(relativePath)
        return try String(contentsOf: file, encoding: .utf8)
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
