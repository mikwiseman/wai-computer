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

    func testInboxViewUsesAppKitTableForFastScrollingRows() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("MacInboxRowsTable("))
        XCTAssertTrue(source.contains("NSTableView"))
        XCTAssertTrue(source.contains("usesAutomaticRowHeights = false"))
        XCTAssertFalse(source.contains("List {"))
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
        XCTAssertTrue(source.contains("Upload File to Inbox"))
        XCTAssertTrue(source.contains("mac-inbox-selected-file"))
        XCTAssertTrue(source.contains("mac-inbox-upload-primary-button"))
        XCTAssertTrue(source.contains("mac-inbox-upload-progress"))
        XCTAssertFalse(source.contains("Attach File"))
        XCTAssertFalse(source.contains("Прикрепить файл"))
    }

    func testInboxSelectedSourceCanAskAndCreateScopedBrainLens() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("MacInboxSourceBrainPanel("))
        XCTAssertTrue(source.contains("apiClient.askBrain(\n                    question: question,\n                    sourceScope: brainSourceScope(for: row)"))
        XCTAssertTrue(source.contains("BrainMapCreateRequest(\n                        prompt: prompt,\n                        origin: \"inbox\",\n                        sourceScope: brainSourceScope(for: row)"))
        XCTAssertTrue(source.contains("onOpenBrainMap(created.id)"))
        XCTAssertTrue(source.contains("\"source_kind\": .string(row.sourceKind.rawValue)"))
        XCTAssertTrue(source.contains("\"source_id\": .string(row.sourceId)"))
    }

    func testInboxCreatedBrainLensOpensSelectedMapInBrain() throws {
        let shellSource = try macSource("WaiComputer/App/MacContentView.swift")
        let brainSource = try macSource("WaiComputer/Features/Brain/MacBrainView.swift")

        XCTAssertTrue(shellSource.contains("@State private var pendingBrainMapId: String?"))
        XCTAssertTrue(shellSource.contains("onOpenBrainMap: openBrainMap"))
        XCTAssertTrue(shellSource.contains("initialMapId: pendingBrainMapId"))
        XCTAssertTrue(shellSource.contains("pendingBrainMapId = mapId\n        selectedSection = .brain"))
        XCTAssertTrue(brainSource.contains("func selectInitialMap(_ mapId: String?)"))
        XCTAssertTrue(brainSource.contains("selectedMapId = mapId"))
    }

    func testGeneratedBrainMapsShowLiveFreshnessBeforeDiagramPreview() throws {
        let source = try macSource("WaiComputer/Features/Brain/MacBrainView.swift")

        guard
            let statusRange = source.range(of: "generatedLiveStatus(revision, projection: projection)"),
            let previewRange = source.range(of: "generatedDiagramPreview(projection)")
        else {
            XCTFail("Generated Brain maps should show live status before the diagram preview.")
            return
        }

        XCTAssertLessThan(statusRange.lowerBound, previewRange.lowerBound)
        XCTAssertTrue(source.contains("\"Updated from sources\""))
        XCTAssertTrue(source.contains("\"No source changes\""))
        XCTAssertTrue(source.contains("\"Newest source \\(weeks) weeks old\""))
        XCTAssertTrue(source.contains("\"Ask what changed before relying on it.\""))
        XCTAssertTrue(source.contains("mapChangeDetail(revision.diff)"))
        XCTAssertTrue(source.contains("mapWatchText(revision, projection: projection)"))
    }

    func testInboxCreatePaneDefaultsToFocusedUploadMode() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("@State private var focusedCreateMode: InboxCreateMode = .file"))
        XCTAssertTrue(source.contains("isActive: focusedCreateMode == .file"))
        XCTAssertTrue(source.contains("case .file:"))
        XCTAssertFalse(source.contains("activeCreateMode"))
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
        XCTAssertBefore("object: \"brain\"", ".keyboardShortcut(\"2\", modifiers: .command)", in: source)
        XCTAssertBefore("object: \"trash\"", ".keyboardShortcut(\"3\", modifiers: .command)", in: source)
        XCTAssertBefore("object: \"history\"", ".keyboardShortcut(\"4\", modifiers: .command)", in: source)
        XCTAssertBefore("object: \"dictionary\"", ".keyboardShortcut(\"5\", modifiers: .command)", in: source)
        XCTAssertTrue(source.contains("CommandMenu(t(\"Navigate\", \"Переход\"))"))
        XCTAssertTrue(source.contains("Button(t(\"New Folder\", \"Новая папка\"))"))
        XCTAssertTrue(source.contains(".keyboardShortcut(\"n\", modifiers: [.command, .shift])"))
    }

    func testInboxTableDisablesHorizontalScrollingAndGridLines() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("scrollView.hasHorizontalScroller = false"))
        XCTAssertTrue(source.contains("tableView.gridStyleMask = []"))
        XCTAssertTrue(source.contains("column.width = scrollView.contentView.bounds.width"))
        XCTAssertTrue(source.contains("tableView.columnAutoresizingStyle = .uniformColumnAutoresizingStyle"))
    }

    func testInboxUsesAutomaticPaginationInsteadOfManualLoadMoreFooter() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("onLoadMore:"))
        XCTAssertTrue(source.contains("contentView.postsBoundsChangedNotifications = true"))
        XCTAssertTrue(source.contains("maybeLoadMoreIfNeeded()"))
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

    func testInboxFocusedCompanionNotifiesWhenTurnCompletes() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("onTurnCompleted: { completion in"))
        XCTAssertTrue(source.contains("MacWaiTaskNotificationCenter.shared.notifyTaskFinished("))
        XCTAssertTrue(source.contains("body: completion.preview ?? t(\"Your Wai task is ready.\", \"Задача Wai готова.\")"))
    }

    func testMacWaiTaskNotificationCenterRequestsPermissionAndSkipsForeground() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacWaiTaskNotificationCenter.swift")

        XCTAssertTrue(source.contains("import UserNotifications"))
        XCTAssertTrue(source.contains("guard !application.isActive else { return }"))
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

    func testRecordingDetailShowsSummaryBeforeTranscriptWithoutTabs() throws {
        let source = try macSource("WaiComputer/Features/Library/MacRecordingDetailView.swift")

        XCTAssertFalse(source.contains("WaiTabBar("))
        XCTAssertBefore("summarySection(detail)", "transcriptSection(detail)", in: source)
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
