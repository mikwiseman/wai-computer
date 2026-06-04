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

    func testInboxPresentsWaiChatAsAgentThread() throws {
        let source = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")

        XCTAssertTrue(source.contains("Ask Wai"))
        XCTAssertTrue(source.contains("Search, remember, plan, or act"))
        XCTAssertFalse(source.contains("New Wai Chat"))
        XCTAssertFalse(source.contains("Wai Chat"))
    }

    func testInboxIsTheOnlyAskWaiAgentSurface() throws {
        let inboxSource = try macSource("WaiComputer/Features/Inbox/MacInboxView.swift")
        let shellSource = try macSource("WaiComputer/App/MacContentView.swift")

        XCTAssertTrue(inboxSource.contains("case .chat:"))
        XCTAssertTrue(inboxSource.contains("CompanionView("))
        XCTAssertTrue(inboxSource.contains("Ask Wai"))
        XCTAssertTrue(inboxSource.contains("Search, remember, plan, or act"))
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
