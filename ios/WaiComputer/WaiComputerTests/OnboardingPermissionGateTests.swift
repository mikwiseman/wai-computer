import XCTest
import UniformTypeIdentifiers
import WaiComputerKit
@testable import WaiComputer

final class OnboardingPermissionGateTests: XCTestCase {
    func testSkipBeforePermissionStopsAtPermissionWhenMicrophoneIsMissing() {
        XCTAssertEqual(
            OnboardingPermissionGate.skipDestination(
                from: .welcome,
                hasMicrophonePermission: false
            ),
            .permission
        )
        XCTAssertEqual(
            OnboardingPermissionGate.skipDestination(
                from: .transcribe,
                hasMicrophonePermission: false
            ),
            .permission
        )
    }

    func testSkipGoesToOptionalVoiceSetupWhenMicrophoneIsGranted() {
        XCTAssertEqual(
            OnboardingPermissionGate.skipDestination(
                from: .welcome,
                hasMicrophonePermission: true
            ),
            .voiceSetup
        )
    }

    func testPermissionPageCannotBeSkippedUntilMicrophoneIsGranted() {
        XCTAssertFalse(
            OnboardingPermissionGate.canSkip(
                from: .permission,
                hasMicrophonePermission: false
            )
        )
        XCTAssertTrue(
            OnboardingPermissionGate.canSkip(
                from: .permission,
                hasMicrophonePermission: true
            )
        )
    }

    func testStoredPagePastPermissionReturnsToPermissionWhenMicrophoneIsMissing() {
        XCTAssertEqual(
            OnboardingPermissionGate.gatedPage(
                current: .voiceSetup,
                hasMicrophonePermission: false
            ),
            .permission
        )
    }

    func testStoredPagePastPermissionIsAllowedAfterMicrophoneGrant() {
        XCTAssertEqual(
            OnboardingPermissionGate.gatedPage(
                current: .voiceSetup,
                hasMicrophonePermission: true
            ),
            .voiceSetup
        )
    }

    func testWorkspaceSectionsPreservePersistedTabValues() {
        XCTAssertNil(IOSWorkspaceSection.inbox.tabValue)
        XCTAssertEqual(IOSWorkspaceSection.record.tabValue, 0)
        XCTAssertEqual(IOSWorkspaceSection.library.tabValue, 1)
        XCTAssertEqual(IOSWorkspaceSection.wai.tabValue, 2)
        XCTAssertEqual(IOSWorkspaceSection.settings.tabValue, 3)
        XCTAssertEqual(IOSWorkspaceSection.materials.tabValue, 4)
        XCTAssertNil(IOSWorkspaceSection.trash.tabValue)
        XCTAssertNil(IOSWorkspaceSection.comparisons.tabValue)
        XCTAssertNil(IOSWorkspaceSection.folder("folder-1").tabValue)
        XCTAssertNil(IOSWorkspaceSection.history.tabValue)
        XCTAssertNil(IOSWorkspaceSection.dictionary.tabValue)
        XCTAssertNil(IOSWorkspaceSection.search.tabValue)
        XCTAssertEqual(IOSWorkspaceSection(tabValue: 4), .materials)
        XCTAssertNil(IOSWorkspaceSection(tabValue: 5))
        XCTAssertEqual(IOSWorkspaceSection.inbox.id, "inbox")
        XCTAssertEqual(IOSWorkspaceSection.folder("folder-1").id, "folder-folder-1")
    }

    func testWorkspaceOnlySectionsFallbackToCompactTabs() {
        XCTAssertEqual(IOSWorkspaceSection.inbox.compactTabValue, 1)
        XCTAssertEqual(IOSWorkspaceSection.history.compactTabValue, 3)
        XCTAssertEqual(IOSWorkspaceSection.dictionary.compactTabValue, 3)
        XCTAssertEqual(IOSWorkspaceSection.trash.compactTabValue, 1)
        XCTAssertEqual(IOSWorkspaceSection.comparisons.compactTabValue, 4)
        XCTAssertEqual(IOSWorkspaceSection.folder("folder-1").compactTabValue, 1)
        XCTAssertEqual(IOSWorkspaceSection.search.compactTabValue, 1)
    }

    func testWorkspaceRoutesMacNavigationTargetsToExistingIOSSurfaces() {
        XCTAssertEqual(IOSWorkspaceSection.routeTarget("inbox"), .inbox)
        XCTAssertEqual(IOSWorkspaceSection.routeTarget("allRecordings"), .inbox)
        XCTAssertEqual(IOSWorkspaceSection.routeTarget("trash"), .trash)
        XCTAssertEqual(IOSWorkspaceSection.routeTarget("search"), .search)
        XCTAssertEqual(IOSWorkspaceSection.routeTarget("content"), .inbox)
        XCTAssertEqual(IOSWorkspaceSection.routeTarget("materials"), .materials)
        XCTAssertEqual(IOSWorkspaceSection.routeTarget("comparisons"), .comparisons)
        XCTAssertEqual(IOSWorkspaceSection.routeTarget("agents"), .wai)
        XCTAssertEqual(IOSWorkspaceSection.routeTarget("history"), .history)
        XCTAssertEqual(IOSWorkspaceSection.routeTarget("dictionary"), .dictionary)
        XCTAssertNil(IOSWorkspaceSection.routeTarget("unknown"))
    }

    func testIPadWorkspaceSidebarFooterShowsAccountStatusAndSettingsRoute() throws {
        let source = try iosSource("WaiComputer/App/ContentView.swift")

        XCTAssertTrue(source.contains("@EnvironmentObject private var appState: AppState"))
        XCTAssertTrue(source.contains("IOSWorkspaceSidebarFooter("))
        XCTAssertTrue(source.contains("user: appState.currentUser"))
        XCTAssertTrue(source.contains("isSettingsSelected: currentSection == .settings"))
        XCTAssertTrue(source.contains("onOpenSettings: { selectedSection = .settings }"))
        XCTAssertTrue(source.contains("let user: User?"))
        XCTAssertTrue(source.contains("let isSettingsSelected: Bool"))
        XCTAssertTrue(source.contains("let onOpenSettings: () -> Void"))
        XCTAssertTrue(source.contains("ios-workspace-account-footer"))
        XCTAssertTrue(source.contains("ios-workspace-account-email"))
        XCTAssertTrue(source.contains("ios-workspace-account-status"))
        XCTAssertTrue(source.contains("ios-workspace-footer-settings"))
        XCTAssertTrue(source.contains("ios-workspace-version-footer"))
    }

    @MainActor
    func testMaterialsImportTypesCoverMacInboxFileCaptureKinds() {
        let types = ContentFeedViewModel.importContentTypes
        XCTAssertTrue(types.contains(.pdf))
        XCTAssertTrue(types.contains(.plainText))
        XCTAssertTrue(types.contains(.audio))
        XCTAssertTrue(types.contains(.movie))
        XCTAssertImportTypes(types, includeExtension: "md")
        XCTAssertImportTypes(types, includeExtension: "opus")
    }

    @MainActor
    func testFolderScopedMaterialsFixturesOnlyShowFolderItems() {
        let scopedModel = ContentFeedViewModel(
            apiClient: APIClient(baseURL: URL(string: "https://example.com")!),
            folderId: IOSScreenshotFixtures.productFolderId
        )
        scopedModel.loadScreenshotFixtures()

        XCTAssertEqual(scopedModel.entries.map(\.id), ["item-1"])
        XCTAssertTrue(scopedModel.entries.allSatisfy {
            $0.folderId == IOSScreenshotFixtures.productFolderId
        })

        let unscopedModel = ContentFeedViewModel(
            apiClient: APIClient(baseURL: URL(string: "https://example.com")!)
        )
        unscopedModel.loadScreenshotFixtures()

        XCTAssertEqual(
            unscopedModel.entries.map(\.id),
            IOSScreenshotFixtures.itemListResponse.items.map(\.id)
        )
    }

    func testMaterialsSearchSurfacesErrorsInsteadOfEmptyFallback() throws {
        let modelSource = try iosSource("WaiComputer/Features/Materials/ContentFeedViewModel.swift")
        let viewSource = try iosSource("WaiComputer/Features/Materials/MaterialsView.swift")

        XCTAssertTrue(modelSource.contains("searchResults = try await apiClient.unifiedSearch(query: q).results"))
        XCTAssertTrue(modelSource.contains("errorMessage = error.userFacingMessage(context: .generic)"))
        XCTAssertTrue(viewSource.contains("if let error = currentError"))
        XCTAssertTrue(viewSource.contains("feed.errorMessage = nil"))
        XCTAssertFalse(modelSource.contains("(try? await apiClient.unifiedSearch(query: q).results) ?? []"))
    }

    func testCompactMaterialsExposeMacStyleInlineCaptureAndKindFilters() throws {
        let feedSource = try iosSource("WaiComputer/Features/Materials/CapturedFeedView.swift")
        let modelSource = try iosSource("WaiComputer/Features/Materials/ContentFeedViewModel.swift")

        XCTAssertTrue(feedSource.contains("CapturedFeedKindFilter"))
        XCTAssertTrue(feedSource.contains("private var inlineCapturePanel"))
        XCTAssertTrue(feedSource.contains("materials-compact-capture-panel"))
        XCTAssertTrue(feedSource.contains("materials-inline-draft-field"))
        XCTAssertTrue(feedSource.contains("materials-inline-upload-button"))
        XCTAssertTrue(feedSource.contains("materials-kind-filter-chips"))
        XCTAssertTrue(feedSource.contains("Task { await model.setKind(filter.kind) }"))
        XCTAssertTrue(modelSource.contains("kind == nil || item.kind == kind"))
        XCTAssertTrue(modelSource.contains("if IOSTestingMode.current.isScreenshot"))
        XCTAssertFalse(feedSource.contains("Tap + to save a link"))
    }

    func testCapturedFeedUsesAdaptiveCapturePanelForRegularSplitPane() throws {
        let feedSource = try iosSource("WaiComputer/Features/Materials/CapturedFeedView.swift")

        XCTAssertTrue(feedSource.contains("@Environment(\\.horizontalSizeClass) private var horizontalSizeClass"))
        XCTAssertTrue(feedSource.contains("private var isRegularSplitPane"))
        XCTAssertTrue(feedSource.contains("private var regularCapturePanel"))
        XCTAssertTrue(feedSource.contains("private var compactCapturePanel"))
        XCTAssertTrue(feedSource.contains("private var captureActions"))
        XCTAssertTrue(feedSource.contains("materials-regular-capture-panel"))
        XCTAssertTrue(feedSource.contains("materials-compact-capture-panel"))
        XCTAssertTrue(feedSource.contains("materials-capture-actions"))
        XCTAssertTrue(feedSource.contains("selectedMaterialId != nil && horizontalSizeClass == .regular"))
        XCTAssertTrue(feedSource.contains("filterChips\n                .padding(.top, Spacing.xxs)"))
        XCTAssertTrue(feedSource.contains("ViewThatFits(in: .horizontal)"))
    }

    func testMaterialsScreenshotModeCanLaunchDirectlyIntoRegularWorkspace() throws {
        let appSource = try iosSource("WaiComputer/App/WaiComputerApp.swift")
        let contentSource = try iosSource("WaiComputer/App/ContentView.swift")

        XCTAssertTrue(appSource.contains("case materials"))
        XCTAssertTrue(contentSource.contains("case .materials:\n            return .materials"))
    }

    func testAddAnythingSheetUsesMacStyleRegularLayout() throws {
        let source = try iosSource("WaiComputer/Features/Materials/AddAnythingSheet.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var horizontalSizeClass"))
        XCTAssertTrue(source.contains("@Environment(\\.dismiss) private var dismiss"))
        XCTAssertTrue(source.contains("private var sheetContent"))
        XCTAssertTrue(source.contains("private var prefersRegularLayout"))
        XCTAssertTrue(source.contains("UIDevice.current.userInterfaceIdiom == .pad"))
        XCTAssertTrue(source.contains("private var regularSheetLayout"))
        XCTAssertTrue(source.contains("private var compactSheetLayout"))
        XCTAssertTrue(source.contains("private var editorCard"))
        XCTAssertTrue(source.contains(".frame(minHeight: prefersRegularLayout ? 220 : 160)"))
        XCTAssertTrue(source.contains(".padding(prefersRegularLayout ? Spacing.md : 0)"))
        XCTAssertTrue(source.contains("add-anything-regular-layout"))
        XCTAssertTrue(source.contains("add-anything-compact-layout"))
        XCTAssertTrue(source.contains("add-anything-editor"))
        XCTAssertTrue(source.contains(".presentationDetents([.medium, .large])"))
        XCTAssertTrue(source.contains("dismiss()"))
    }

    func testMaterialsViewUsesRegularWidthMacStyleSplitDetail() throws {
        let source = try iosSource("WaiComputer/Features/Materials/MaterialsView.swift")
        let feedSource = try iosSource("WaiComputer/Features/Materials/CapturedFeedView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var horizontalSizeClass"))
        XCTAssertTrue(source.contains("@State private var selectedMaterialId: String?"))
        XCTAssertTrue(source.contains("regularMaterialsLayout"))
        XCTAssertTrue(source.contains("compactMaterialsLayout"))
        XCTAssertTrue(source.contains("materials-regular-layout"))
        XCTAssertTrue(source.contains("materials-regular-list-pane"))
        XCTAssertTrue(source.contains("materials-regular-detail-pane"))
        XCTAssertTrue(source.contains("materials-regular-placeholder"))
        XCTAssertTrue(source.contains("selectedMaterialId: $selectedMaterialId"))
        XCTAssertTrue(source.contains("ItemDetailView(itemId: id, apiClient: apiClient)"))
        XCTAssertTrue(feedSource.contains("let selectedMaterialId: Binding<String?>?"))
        XCTAssertTrue(feedSource.contains("selectedMaterialId?.wrappedValue = entry.id"))
        XCTAssertTrue(feedSource.contains("selectedMaterialId?.wrappedValue == entry.id"))
    }

    func testIOSInboxUsesIPadSplitDetailWithoutBreakingCompactPushNavigation() throws {
        let source = try iosSource("WaiComputer/Features/Materials/MaterialsView.swift")
        let itemDetailSource = try iosSource("WaiComputer/Features/Materials/ItemDetailView.swift")
        let appSource = try iosSource("WaiComputer/App/WaiComputerApp.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass)"))
        XCTAssertTrue(source.contains("private enum IOSInboxDetailSelection"))
        XCTAssertTrue(source.contains("private var regularInboxLayout"))
        XCTAssertTrue(source.contains("private var compactInboxLayout"))
        XCTAssertTrue(source.contains("ios-inbox-regular-layout"))
        XCTAssertTrue(source.contains("ios-inbox-list-pane"))
        XCTAssertTrue(source.contains("ios-inbox-regular-detail"))
        XCTAssertTrue(source.contains("IOSInboxRegularDetailPlaceholder"))
        XCTAssertTrue(source.contains("selectedDetail = .recording(recording.id)"))
        XCTAssertTrue(source.contains("selectedDetail = .material(entry.id)"))
        XCTAssertTrue(source.contains("selectedDetail = nil"))
        XCTAssertTrue(source.contains("NavigationLink {\n                recordingDetailView(for: recording)"))
        XCTAssertTrue(source.contains("NavigationLink {\n                materialDetailView(for: entry)"))
        XCTAssertTrue(source.contains(".navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)"))
        XCTAssertTrue(itemDetailSource.contains("IOSScreenshotFixtures.item(id: itemId)"))
        XCTAssertTrue(appSource.contains("static let items: [Item]"))
        XCTAssertTrue(appSource.contains("static func item(id: String) -> Item"))
    }

    func testIOSItemDetailUsesMacStyleRegularReadingLayout() throws {
        let source = try iosSource("WaiComputer/Features/Materials/ItemDetailView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var horizontalSizeClass"))
        XCTAssertTrue(source.contains("private var isRegularWidth"))
        XCTAssertTrue(source.contains("private func regularItemDetailLayout(_ item: Item) -> some View"))
        XCTAssertTrue(source.contains("private func compactItemDetailLayout(_ item: Item) -> some View"))
        XCTAssertTrue(source.contains("ios-item-detail-regular-layout"))
        XCTAssertTrue(source.contains("ios-item-detail-regular-header"))
        XCTAssertTrue(source.contains("ios-item-detail-summary-section"))
        XCTAssertTrue(source.contains("ios-item-detail-original-section"))
        XCTAssertTrue(source.contains("summarySection(item)"))
        XCTAssertTrue(source.contains("originalMaterialSection(item)"))
        XCTAssertTrue(source.contains("sourceLabel(item.source)"))
        XCTAssertTrue(source.contains("formattedDate(item.occurredAt ?? item.createdAt)"))
        XCTAssertTrue(source.contains("IOSDateFormatting.listTimestamp("))
        XCTAssertTrue(source.contains("ScrollView {\n            VStack(alignment: .leading, spacing: Spacing.lg)"))
        XCTAssertTrue(source.contains(".navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)"))
    }

    func testIOSTrashUsesIPadSplitDetailWithoutBreakingCompactPushNavigation() throws {
        let source = try iosSource("WaiComputer/Features/Library/LibraryView.swift")
        let appSource = try iosSource("WaiComputer/App/WaiComputerApp.swift")
        let detailModelSource = try iosSource("WaiComputer/Features/Library/RecordingDetailViewModel.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var trashHorizontalSizeClass"))
        XCTAssertTrue(source.contains("@State private var selectedTrashRecordingId: String?"))
        XCTAssertTrue(source.contains("private var regularTrashLayout"))
        XCTAssertTrue(source.contains("private var compactTrashList"))
        XCTAssertTrue(source.contains("ios-trash-regular-layout"))
        XCTAssertTrue(source.contains("ios-trash-list-pane"))
        XCTAssertTrue(source.contains("ios-trash-detail-pane"))
        XCTAssertTrue(source.contains("ios-trash-placeholder"))
        XCTAssertTrue(source.contains("selectedTrashRecordingId = recording.id"))
        XCTAssertTrue(source.contains("selectedTrashRecordingId = nil"))
        XCTAssertTrue(source.contains("RecordingDetailView("))
        XCTAssertTrue(source.contains("isTrash: true"))
        XCTAssertTrue(source.contains("NavigationLink(destination: trashDetailView(for: recording))"))
        XCTAssertTrue(appSource.contains("static func recordingDetail(id: String) -> RecordingDetail"))
        XCTAssertTrue(appSource.contains("trashedRecordings.first(where: { $0.id == id })"))
        XCTAssertTrue(detailModelSource.contains("IOSScreenshotFixtures.recordingDetail(id: recordingId)"))
    }

    func testIOSLibraryUsesIPadSplitDetailWithoutBreakingCompactPushNavigation() throws {
        let source = try iosSource("WaiComputer/Features/Library/LibraryView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var libraryHorizontalSizeClass"))
        XCTAssertTrue(source.contains("@State private var selectedLibraryRecordingId: String?"))
        XCTAssertTrue(source.contains("private var regularLibraryLayout"))
        XCTAssertTrue(source.contains("private var compactLibraryList"))
        XCTAssertTrue(source.contains("ios-library-regular-layout"))
        XCTAssertTrue(source.contains("ios-library-list-pane"))
        XCTAssertTrue(source.contains("ios-library-detail-pane"))
        XCTAssertTrue(source.contains("ios-library-placeholder"))
        XCTAssertTrue(source.contains("selectedLibraryRecordingId = recording.id"))
        XCTAssertTrue(source.contains("selectedLibraryRecordingId = nil"))
        XCTAssertTrue(source.contains("regularLibraryDetailPane"))
        XCTAssertTrue(source.contains("recordingDetailView(for: recording)"))
        XCTAssertTrue(source.contains("NavigationLink(destination: recordingDetailView(for: recording))"))
        XCTAssertTrue(source.contains(".navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)"))
    }

    func testIOSRecordingRowsUseMacStyleMetadataLayout() throws {
        let source = try iosSource("WaiComputer/Features/Library/LibraryView.swift")
        let rowSource = try sourceSlice(
            source,
            startingAt: "struct RecordingRow: View",
            endingBefore: "private var statusColor"
        )

        XCTAssertTrue(rowSource.contains("VStack(alignment: .leading, spacing: Spacing.xs)"))
        XCTAssertTrue(rowSource.contains("HStack(spacing: Spacing.sm)"))
        XCTAssertTrue(rowSource.contains(".font(Typography.headingMedium)"))
        XCTAssertTrue(rowSource.contains(".truncationMode(.tail)"))
        XCTAssertTrue(rowSource.contains(".layoutPriority(1)"))
        XCTAssertTrue(rowSource.contains(".font(Typography.label)"))
        XCTAssertTrue(rowSource.contains(".minimumScaleFactor(0.85)"))
        XCTAssertTrue(rowSource.contains(".fixedSize(horizontal: true, vertical: false)"))
        XCTAssertTrue(rowSource.contains(".fill(Palette.typeColor(recording.type))"))
        XCTAssertTrue(rowSource.contains("IOSDateFormatting.listTimestamp("))
        XCTAssertTrue(rowSource.contains("IOSDateFormatting.duration(seconds:"))
        XCTAssertTrue(rowSource.contains(".font(Typography.mono)"))
        XCTAssertTrue(rowSource.contains(".foregroundStyle(Palette.textSecondary)"))
        XCTAssertTrue(rowSource.contains(".frame(maxWidth: .infinity, minHeight: rowMinHeight, alignment: .leading)"))
        XCTAssertFalse(rowSource.contains(".font(.headline)"))
        XCTAssertFalse(rowSource.contains(".font(.caption)"))
        XCTAssertFalse(rowSource.contains(".foregroundStyle(.secondary)"))
    }

    @MainActor
    func testIOSLibraryViewModelPatchesCachedRowsFromFetchedDetail() {
        let viewModel = LibraryViewModel()
        let createdAt = Date(timeIntervalSince1970: 1_789_444_400)
        viewModel.recordings = [
            Recording(
                id: "rec-active",
                title: nil,
                type: .meeting,
                status: .processing,
                durationSeconds: nil,
                createdAt: createdAt
            )
        ]
        viewModel.trashedRecordings = [
            Recording(
                id: "rec-trash",
                title: "Old Trash",
                type: .note,
                status: .ready,
                durationSeconds: 5,
                deletedAt: createdAt,
                createdAt: createdAt
            )
        ]

        viewModel.applyRecordingDetail(
            RecordingDetail(
                id: "rec-active",
                title: "Реформа продуктовых процессов с AI",
                type: .meeting,
                status: .ready,
                durationSeconds: 563,
                language: "ru",
                createdAt: createdAt,
                segments: [Segment(id: "s1", content: "Готовая расшифровка.")]
            )
        )
        viewModel.applyRecordingDetail(
            RecordingDetail(
                id: "rec-trash",
                title: "Trash Generated Title",
                type: .note,
                status: .failed,
                failureCode: "failed_upload",
                failureMessage: "Upload failed",
                durationSeconds: 5,
                deletedAt: createdAt,
                createdAt: createdAt
            )
        )

        XCTAssertEqual(viewModel.recordings.first?.title, "Реформа продуктовых процессов с AI")
        XCTAssertEqual(viewModel.recordings.first?.status, .ready)
        XCTAssertEqual(viewModel.recordings.first?.durationSeconds, 563)
        XCTAssertEqual(viewModel.recordings.first?.language, "ru")
        XCTAssertEqual(viewModel.trashedRecordings.first?.title, "Trash Generated Title")
        XCTAssertEqual(viewModel.trashedRecordings.first?.status, .failed)
        XCTAssertEqual(viewModel.trashedRecordings.first?.failureCode, "failed_upload")
        XCTAssertEqual(viewModel.trashedRecordings.first?.failureMessage, "Upload failed")
    }

    func testIOSRecordingDetailRefreshPatchesLibraryRows() throws {
        let librarySource = try iosSource("WaiComputer/Features/Library/LibraryView.swift")
        let detailSource = try iosSource("WaiComputer/Features/Library/RecordingDetailView.swift")

        XCTAssertTrue(librarySource.contains("func applyRecordingDetail(_ detail: RecordingDetail)"))
        XCTAssertTrue(librarySource.contains("viewModel.applyRecordingDetail(detail)"))
        XCTAssertTrue(detailSource.contains("var onDetailChange: ((RecordingDetail) -> Void)?"))
        XCTAssertTrue(detailSource.contains(".onReceive(viewModel.$detail.compactMap { $0 })"))
        XCTAssertTrue(librarySource.contains("if importedRecording.id == detail.id"))
        XCTAssertTrue(librarySource.contains("self.importedRecording = Recording(detail: detail)"))
        let detailChangeIndex = try XCTUnwrap(librarySource.range(of: "onDetailChange: { detail in")?.lowerBound)
        let renameIndex = try XCTUnwrap(librarySource.range(of: "onDidRename:")?.lowerBound)
        XCTAssertLessThan(detailChangeIndex, renameIndex)
    }

    func testIOSUnifiedSearchUsesIPadSplitDetailWithoutBreakingCompactPushNavigation() throws {
        let source = try iosSource("WaiComputer/Features/Search/SearchView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass)"))
        XCTAssertTrue(source.contains("@State private var selectedHit: UnifiedHit?"))
        XCTAssertTrue(source.contains("private var regularSearchLayout"))
        XCTAssertTrue(source.contains("private var compactSearchLayout"))
        XCTAssertTrue(source.contains("ios-unified-search-regular-layout"))
        XCTAssertTrue(source.contains("ios-unified-search-results-pane"))
        XCTAssertTrue(source.contains("ios-unified-search-detail-pane"))
        XCTAssertTrue(source.contains("IOSUnifiedSearchDetailPlaceholder"))
        XCTAssertTrue(source.contains("selectedHit = hit"))
        XCTAssertTrue(source.contains("selectedHit = nil"))
        XCTAssertTrue(source.contains("destination(for: selectedHit)"))
        XCTAssertTrue(source.contains("NavigationLink {\n                destination(for: hit)"))
        XCTAssertTrue(source.contains(".navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)"))
    }

    func testIOSLibrarySearchRowsUseMacStyleResultPresentation() throws {
        let source = try iosSource("WaiComputer/Features/Search/SearchView.swift")
        let rowSource = try sourceSlice(
            source,
            startingAt: "struct SearchResultRow: View",
            endingBefore: "enum SearchPresentation"
        )

        XCTAssertTrue(rowSource.contains("Image(systemName: \"waveform\")"))
        XCTAssertTrue(rowSource.contains(".font(Typography.caption)"))
        XCTAssertTrue(rowSource.contains(".foregroundStyle(Palette.typeColor(result.recordingType))"))
        XCTAssertTrue(rowSource.contains(".font(Typography.headingMedium)"))
        XCTAssertTrue(rowSource.contains(".foregroundStyle(Palette.textPrimary)"))
        XCTAssertTrue(rowSource.contains(".layoutPriority(1)"))
        XCTAssertTrue(rowSource.contains("localizedKind"))
        XCTAssertTrue(rowSource.contains(".font(Typography.labelSmall)"))
        XCTAssertTrue(rowSource.contains(".foregroundStyle(Palette.textTertiary)"))
        XCTAssertTrue(rowSource.contains(".textCase(.uppercase)"))
        XCTAssertTrue(rowSource.contains(".font(Typography.reading)"))
        XCTAssertTrue(rowSource.contains(".lineSpacing(5)"))
        XCTAssertTrue(rowSource.contains(".foregroundStyle(Palette.textSecondary)"))
        XCTAssertFalse(rowSource.contains("scoreColor"))
        XCTAssertFalse(rowSource.contains(".font(.headline)"))
        XCTAssertFalse(rowSource.contains(".font(.subheadline)"))
        XCTAssertFalse(rowSource.contains(".foregroundStyle(.secondary)"))
    }

    @MainActor
    func testIOSDictationStoresMatchMacCorrectionAndLearningContracts() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let historyStore = DictationHistoryStore(
            fileURL: directory.appendingPathComponent("history.json"),
            tombstonesURL: directory.appendingPathComponent("history_tombstones.json")
        )
        historyStore.add(rawText: "open sigma", cleanedText: nil, durationSeconds: 3)

        let originalRevision = historyStore.entriesRevision
        let entry = try XCTUnwrap(historyStore.entries.first)
        XCTAssertTrue(historyStore.applyCorrection(to: entry, correctedText: "open Figma"))
        XCTAssertGreaterThan(historyStore.entriesRevision, originalRevision)
        XCTAssertEqual(historyStore.entries.first?.displayText, "open Figma")
        XCTAssertEqual(historyStore.entries.first?.wordCount, 2)
        XCTAssertFalse(historyStore.applyCorrection(to: historyStore.entries[0], correctedText: "open Figma"))

        let dictionaryStore = DictationDictionaryStore(
            fileURL: directory.appendingPathComponent("dictionary.json"),
            tombstonesURL: directory.appendingPathComponent("dictionary_tombstones.json")
        )
        var hintReasons: [String] = []
        dictionaryStore.onRealtimeHintsChanged = { hintReasons.append($0) }

        XCTAssertTrue(dictionaryStore.add(word: "sigma"))
        dictionaryStore.learnReplacement(word: "sigma", replacement: "Figma")
        let learned = try XCTUnwrap(dictionaryStore.words.first)
        XCTAssertEqual(dictionaryStore.words.count, 1)
        XCTAssertEqual(learned.word, "sigma")
        XCTAssertEqual(learned.replacement, "Figma")
        XCTAssertEqual(learned.origin, "learned")
        XCTAssertTrue(learned.isLearned)
        XCTAssertEqual(dictionaryStore.vocabularyList, ["sigma", "Figma"])
        XCTAssertEqual(
            dictionaryStore.realtimeHints.replacements,
            [RealtimeTranscriptionReplacement(find: "sigma", replace: "Figma")]
        )
        XCTAssertEqual(dictionaryStore.applyReplacements(to: "open sigma"), "open Figma")
        XCTAssertEqual(dictionaryStore.applyReplacements(to: "open why, computer"), "open why, computer")

        dictionaryStore.learnReplacement(word: "why computer", replacement: "WaiComputer")
        XCTAssertEqual(dictionaryStore.applyReplacements(to: "open why, computer"), "open WaiComputer")

        XCTAssertTrue(dictionaryStore.update(try XCTUnwrap(dictionaryStore.words.first), newWord: "Figma", newReplacement: nil))
        XCTAssertTrue(hintReasons.contains("dictionary_add"))
        XCTAssertTrue(hintReasons.contains("dictionary_learn_replacement"))
        XCTAssertTrue(hintReasons.contains("dictionary_update"))

        historyStore.loadScreenshotFixtures()
        dictionaryStore.loadScreenshotFixtures()
        XCTAssertEqual(historyStore.entries.map(\.id), IOSScreenshotFixtures.dictationHistoryEntries.map(\.id))
        XCTAssertEqual(dictionaryStore.words.map(\.id), IOSScreenshotFixtures.dictionaryWords.map(\.id))
    }

    func testIOSDictationViewsExposeMacLearningAndEditFlows() throws {
        let appSource = try iosSource("WaiComputer/App/WaiComputerApp.swift")
        let contentSource = try iosSource("WaiComputer/App/ContentView.swift")
        let historyViewSource = try iosSource("WaiComputer/Features/Dictation/DictationHistoryView.swift")
        let dictionaryViewSource = try iosSource("WaiComputer/Features/Dictation/DictationDictionaryView.swift")
        let historyStoreSource = try iosSource("WaiComputer/Features/Dictation/DictationHistoryStore.swift")
        let dictionaryStoreSource = try iosSource("WaiComputer/Features/Dictation/DictationDictionaryStore.swift")

        XCTAssertTrue(appSource.contains("struct IOSLexiconChecker: LexiconChecking"))
        XCTAssertTrue(appSource.contains("UITextChecker().rangeOfMisspelledWord"))
        XCTAssertTrue(appSource.contains("@StateObject private var learningEngine = DictionaryLearningEngine(lexicon: IOSLexiconChecker())"))
        XCTAssertTrue(appSource.contains(".environmentObject(learningEngine)"))
        XCTAssertTrue(appSource.contains("case history"))
        XCTAssertTrue(appSource.contains("case dictionary"))
        XCTAssertTrue(appSource.contains("static let dictationHistoryEntries: [DictationHistoryEntry]"))
        XCTAssertTrue(appSource.contains("static let dictionaryWords: [DictionaryWord]"))
        XCTAssertTrue(appSource.contains("prepareScreenshotFixturesIfNeeded()"))
        XCTAssertTrue(contentSource.contains("private var screenshotWorkspaceSection: IOSWorkspaceSection?"))
        XCTAssertTrue(contentSource.contains("case .history:"))
        XCTAssertTrue(contentSource.contains("case .dictionary:"))

        XCTAssertTrue(historyStoreSource.contains("func applyCorrection(to entry: DictationHistoryEntry, correctedText: String) -> Bool"))
        XCTAssertTrue(historyStoreSource.contains("private(set) var entriesRevision"))
        XCTAssertTrue(historyStoreSource.contains("func loadScreenshotFixtures()"))
        XCTAssertTrue(historyViewSource.contains("@EnvironmentObject private var learningEngine: DictionaryLearningEngine"))
        XCTAssertTrue(historyViewSource.contains("@Environment(\\.horizontalSizeClass)"))
        XCTAssertTrue(historyViewSource.contains("private func regularHistoryLayout"))
        XCTAssertTrue(historyViewSource.contains("private func compactHistoryList"))
        XCTAssertTrue(historyViewSource.contains("ios-dictation-history-regular-layout"))
        XCTAssertTrue(historyViewSource.contains("ios-dictation-history-regular-header"))
        XCTAssertTrue(historyViewSource.contains("ios-dictation-history-search-field"))
        XCTAssertTrue(historyViewSource.contains("learningEngine.observeEdit(produced: original, edited: correctedText, language: nil)"))
        XCTAssertTrue(historyViewSource.contains("private final class DictationHistoryDisplayCache"))
        XCTAssertTrue(historyViewSource.contains("Image(systemName: \"pencil\")"))

        XCTAssertTrue(dictionaryStoreSource.contains("var origin: String"))
        XCTAssertTrue(dictionaryStoreSource.contains("var isLearned: Bool"))
        XCTAssertTrue(dictionaryStoreSource.contains("func learnReplacement(word: String, replacement: String)"))
        XCTAssertTrue(dictionaryStoreSource.contains("func update(_ word: DictionaryWord, newWord: String, newReplacement: String?) -> Bool"))
        XCTAssertTrue(dictionaryStoreSource.contains("var realtimeHints: DictationRealtimeHints"))
        XCTAssertTrue(dictionaryStoreSource.contains("replacementPattern(for: word.word)"))
        XCTAssertTrue(dictionaryStoreSource.contains("func loadScreenshotFixtures()"))
        XCTAssertTrue(dictionaryViewSource.contains("@EnvironmentObject private var learningEngine: DictionaryLearningEngine"))
        XCTAssertTrue(dictionaryViewSource.contains("@Environment(\\.horizontalSizeClass)"))
        XCTAssertTrue(dictionaryViewSource.contains("private func regularDictionaryLayout"))
        XCTAssertTrue(dictionaryViewSource.contains("private func compactDictionaryList"))
        XCTAssertTrue(dictionaryViewSource.contains("ios-dictation-dictionary-regular-layout"))
        XCTAssertTrue(dictionaryViewSource.contains("ios-dictation-dictionary-regular-header"))
        XCTAssertTrue(dictionaryViewSource.contains("ios-dictation-dictionary-search-field"))
        XCTAssertTrue(dictionaryViewSource.contains("Suggested from your edits"))
        XCTAssertTrue(dictionaryViewSource.contains("dictionaryStore.learnReplacement(word: suggestion.original, replacement: suggestion.corrected)"))
        XCTAssertTrue(dictionaryViewSource.contains("private func beginEdit(_ word: DictionaryWord)"))
        XCTAssertTrue(dictionaryViewSource.contains("private final class DictationDictionaryDisplayCache"))
    }

    func testIOSDictionaryRowsUseReadableMacStyleStackedMetadata() throws {
        let source = try iosSource("WaiComputer/Features/Dictation/DictationDictionaryView.swift")
        let rowSource = try sourceSlice(
            source,
            startingAt: "private func wordRow(_ word: DictionaryWord)",
            endingBefore: "private func badge(label: String, color: Color)"
        )

        XCTAssertTrue(rowSource.contains("HStack(alignment: .top, spacing: Spacing.md)"))
        XCTAssertTrue(rowSource.contains("VStack(alignment: .leading, spacing: Spacing.xs)"))
        XCTAssertTrue(rowSource.contains("Typography.headingMedium"))
        XCTAssertTrue(rowSource.contains("Typography.bodySmall"))
        XCTAssertTrue(rowSource.contains("dictionaryWordBadges(for: word)"))
        XCTAssertTrue(rowSource.contains("RoundedRectangle(cornerRadius: 8, style: .continuous)"))
        XCTAssertTrue(rowSource.contains("Image(systemName: \"xmark.circle.fill\")"))
        XCTAssertFalse(rowSource.contains("HStack(spacing: 8)"))
        XCTAssertFalse(rowSource.contains(".font(.caption2)"))
        XCTAssertFalse(rowSource.contains(".font(.caption)"))
    }

    func testComparisonViewsMatchMacReadableTableAndErrorStates() throws {
        let source = try iosSource("WaiComputer/Features/Materials/ComparisonView.swift")
        let appSource = try iosSource("WaiComputer/App/WaiComputerApp.swift")
        let contentSource = try iosSource("WaiComputer/App/ContentView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var horizontalSizeClass"))
        XCTAssertTrue(source.contains("@State private var selectedComparisonId: String?"))
        XCTAssertTrue(source.contains("private var regularComparisonLayout"))
        XCTAssertTrue(source.contains("private var compactComparisonList"))
        XCTAssertTrue(source.contains("ios-comparison-regular-layout"))
        XCTAssertTrue(source.contains("ios-comparison-list-pane"))
        XCTAssertTrue(source.contains("ios-comparison-detail-pane"))
        XCTAssertTrue(source.contains("ios-comparison-placeholder"))
        XCTAssertTrue(source.contains("selectedComparisonId = entry.id"))
        XCTAssertTrue(source.contains("ComparisonDetailView(apiClient: apiClient, comparisonId: id)"))
        XCTAssertTrue(source.contains("NavigationLink {\n                ComparisonDetailView(apiClient: apiClient, comparisonId: entry.id)"))
        XCTAssertTrue(source.contains("@State private var loadError: String?"))
        XCTAssertTrue(source.contains("Couldn't load comparisons"))
        XCTAssertTrue(source.contains("Couldn't load comparison"))
        XCTAssertTrue(source.contains("entries = try await apiClient.listComparisons()"))
        XCTAssertTrue(source.contains("loadError = error.userFacingMessage(context: .generic)"))
        XCTAssertTrue(source.contains("titleColumnWidth"))
        XCTAssertTrue(source.contains("valueColumnWidth"))
        XCTAssertTrue(source.contains("private func comparisonTableWidth"))
        XCTAssertTrue(source.contains("comparisonTableWidth(columns: columns)"))
        XCTAssertTrue(source.contains("ScrollView(.vertical)"))
        XCTAssertTrue(source.contains("ScrollView(.horizontal)"))
        XCTAssertTrue(source.contains(".defaultScrollAnchor(.topLeading)"))
        XCTAssertTrue(source.contains(".textSelection(.enabled)"))
        XCTAssertTrue(source.contains("ios-comparison-detail-view"))
        XCTAssertTrue(source.contains("ios-comparison-table"))
        XCTAssertTrue(source.contains("compactComparisonCards"))
        XCTAssertTrue(source.contains("ios-comparison-compact-cards"))
        XCTAssertTrue(source.contains("horizontalSizeClass == .compact"))
        XCTAssertTrue(source.contains(".waiCard()"))
        XCTAssertTrue(source.contains("IOSScreenshotFixtures.comparison(id: comparisonId)"))
        XCTAssertTrue(appSource.contains("case comparison"))
        XCTAssertTrue(appSource.contains("static let comparisonSet"))
        XCTAssertTrue(appSource.contains("static let comparisonListEntries"))
        XCTAssertTrue(contentSource.contains("WAICOMPUTER_COMPARISON_ID"))
        XCTAssertTrue(contentSource.contains("ComparisonDetailView("))
        XCTAssertTrue(contentSource.contains("case .comparisons:"))
        XCTAssertTrue(contentSource.contains("ComparisonListView(apiClient: apiClient)"))
        XCTAssertTrue(contentSource.contains("case .comparison:\n            return .comparisons"))
        XCTAssertTrue(contentSource.contains("return [.library, .materials, .comparisons]"))
        XCTAssertFalse(source.contains("entries = (try? await apiClient.listComparisons()) ?? []"))
        XCTAssertFalse(source.contains("Grid(alignment: .topLeading"))
        XCTAssertFalse(source.contains("ScrollView([.horizontal, .vertical])"))
    }

    func testIOSInboxDragItemUsesDeclaredTransferIdentifier() throws {
        XCTAssertEqual(
            UTType.waiIOSInboxMove.identifier,
            "is.waiwai.computer.ios.inbox-move"
        )

        let item = IOSInboxDragItem(kind: .item, id: "item-1")
        let data = try JSONEncoder().encode(item)
        let decoded = try JSONDecoder().decode(IOSInboxDragItem.self, from: data)

        XCTAssertEqual(decoded, item)
    }

    func testIOSWorkspaceSidebarDropsMoveEveryInboxKind() throws {
        let source = try iosSource("WaiComputer/App/ContentView.swift")

        XCTAssertTrue(source.contains("handleInboxDrop(items, folderId: nil)"))
        XCTAssertTrue(source.contains("handleInboxDrop(items, folderId: folder.id)"))
        XCTAssertTrue(source.contains("handleFileDrop(urls, folderId: nil)"))
        XCTAssertTrue(source.contains("handleFileDrop(urls, folderId: folder.id)"))
        XCTAssertTrue(source.contains("apiClient.moveRecording(id: item.id, folderId: folderId)"))
        XCTAssertTrue(source.contains("apiClient.moveItem(id: item.id, folderId: folderId)"))
        XCTAssertTrue(source.contains("apiClient.moveCompanionChat(chatId: item.id, folderId: folderId)"))
        XCTAssertFalse(source.contains("case .chat:\n                        continue"))
    }

    func testRecordingDetailHasRegularWidthMacStyleReadingLayout() throws {
        let source = try iosSource("WaiComputer/Features/Library/RecordingDetailView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass)"))
        XCTAssertTrue(source.contains("regularWidthContent(detail)"))
        XCTAssertTrue(source.contains("compactTabbedContent"))
        XCTAssertTrue(source.contains("recording-detail-regular-layout"))
        XCTAssertTrue(source.contains("regularSummarySection(detail)"))
        XCTAssertTrue(source.contains("regularTranscriptSection(detail)"))
        XCTAssertTrue(source.contains("summary-action-items-ipad"))
        XCTAssertTrue(source.contains("runExport(format: \"txt\", style: \"timestamped\")"))
    }

    func testCompactTranscriptViewMatchesMacCopyHeaderAffordance() throws {
        let source = try iosSource("WaiComputer/Features/Library/TranscriptView.swift")

        XCTAssertTrue(source.contains("Text(t(\"Transcript\", \"Расшифровка\"))"))
        XCTAssertTrue(source.contains("copyTranscriptButton"))
        XCTAssertTrue(source.contains("Label(copied ? t(\"Copied\", \"Скопировано\") : t(\"Copy Transcript\", \"Скопировать расшифровку\"), systemImage: copied ? \"checkmark\" : \"doc.on.doc\")"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"transcript-content\")"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"transcript-copy-menu\")"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"transcript-copy-plain\")"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"transcript-copy-timestamped\")"))
        XCTAssertTrue(source.contains("copyTranscript(style: .plain)"))
        XCTAssertTrue(source.contains("copyTranscript(style: .timestamped)"))
        XCTAssertTrue(source.contains("UIPasteboard.general.string = TranscriptRendering.transcriptText"))
    }

    func testCompactTranscriptSegmentRowsUseMacReadingStyle() throws {
        let source = try iosSource("WaiComputer/Features/Library/TranscriptView.swift")

        XCTAssertTrue(source.contains("struct SegmentView: View"))
        XCTAssertTrue(source.contains("VStack(alignment: .leading, spacing: Spacing.xs)"))
        XCTAssertTrue(source.contains("HStack(spacing: Spacing.sm)"))
        XCTAssertTrue(source.contains(".font(Typography.label)"))
        XCTAssertTrue(source.contains(".foregroundStyle(Palette.textSecondary)"))
        XCTAssertTrue(source.contains("Text(segment.formattedTimestamp)"))
        XCTAssertTrue(source.contains(".font(Typography.mono)"))
        XCTAssertTrue(source.contains(".foregroundStyle(Palette.textTertiary)"))
        XCTAssertTrue(source.contains(".font(Typography.reading)"))
        XCTAssertTrue(source.contains(".lineSpacing(6)"))
        XCTAssertTrue(source.contains(".foregroundStyle(Palette.textPrimary)"))
        XCTAssertTrue(source.contains(".frame(maxWidth: .infinity, alignment: .leading)"))
        XCTAssertFalse(source.contains(".foregroundStyle(.blue)"))
        XCTAssertFalse(source.contains(".font(.body)"))
        XCTAssertFalse(source.contains(".background(Color.gray.opacity(0.05))"))
    }

    func testCompactRecordingDetailToolbarExposesTimestampedTextExport() throws {
        let source = try iosSource("WaiComputer/Features/Library/RecordingDetailView.swift")

        XCTAssertTrue(source.contains("compactExportMenu"))
        XCTAssertTrue(source.contains("Task { await runExport(format: \"txt\", style: \"timestamped\") }"))
        XCTAssertTrue(source.contains("Label(t(\"Plain Text + timestamps (.txt)\", \"Текст с тайм-кодами (.txt)\"), systemImage: \"clock\")"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"recording-detail-compact-export-menu\")"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"recording-detail-export-timestamped-text\")"))
    }

    func testRegularTranscriptCopyMenuUsesMacLabeledAffordance() throws {
        let source = try iosSource("WaiComputer/Features/Library/RecordingDetailView.swift")

        XCTAssertTrue(source.contains("private func transcriptCopyMenu(_ segments: [Segment]) -> some View"))
        XCTAssertTrue(source.contains("Label(copiedSection == \"transcript-all\" ? t(\"Copied\", \"Скопировано\") : t(\"Copy Transcript\", \"Скопировать расшифровку\"), systemImage: copiedSection == \"transcript-all\" ? \"checkmark\" : \"doc.on.doc\")"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"transcript-copy-menu\")"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"transcript-copy-plain\")"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"transcript-copy-timestamped\")"))
    }

    func testCompactSummaryCopyMatchesMacLabeledActionAndIncludesActionItems() throws {
        let source = try iosSource("WaiComputer/Features/Library/RecordingDetailView.swift")

        XCTAssertTrue(source.contains("SummaryTabView(\n                    summary: viewModel.detail?.summary,\n                    actionItems: viewModel.detail?.actionItems ?? []"))
        XCTAssertTrue(source.contains("let actionItems: [ActionItem]"))
        XCTAssertTrue(source.contains("private func summaryHeader(_ summary: Summary) -> some View"))
        XCTAssertTrue(source.contains("Label(copiedSection == \"summary-all\" ? t(\"Copied\", \"Скопировано\") : t(\"Copy Summary\", \"Скопировать сводку\"), systemImage: copiedSection == \"summary-all\" ? \"checkmark\" : \"doc.on.doc\")"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"summary-copy-menu\")"))
        XCTAssertTrue(source.contains("private func fullSummaryText(_ summary: Summary, actionItems: [ActionItem]) -> String"))
        XCTAssertTrue(source.contains("visibleActionItems.map { \"- \\($0.task)\" }.joined(separator: \"\\n\")"))
    }

    func testCompactSummaryRendersInlineVisibleActionItemsLikeMac() throws {
        let source = try iosSource("WaiComputer/Features/Library/RecordingDetailView.swift")

        XCTAssertTrue(source.contains("private func visibleSummaryActionItems(_ actionItems: [ActionItem]) -> [ActionItem]"))
        XCTAssertTrue(source.contains("actionItems.filter { $0.status != .cancelled }"))
        XCTAssertTrue(source.contains("regularActionItemsSection(visibleActionItems)"))
        XCTAssertTrue(source.contains("private var visibleActionItems: [ActionItem] {\n        visibleSummaryActionItems(actionItems)\n    }"))
        XCTAssertTrue(source.contains("summaryActionItemsSection(visibleActionItems)"))
        XCTAssertTrue(source.contains("private func summaryActionItemsSection(_ actionItems: [ActionItem]) -> some View"))
        XCTAssertTrue(source.contains("SectionView(title: t(\"Action Items\", \"Задачи\"))"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"summary-action-items\")"))
        XCTAssertTrue(source.contains("section: \"summary-action-items\""))
        XCTAssertTrue(source.contains("visibleActionItems.map { \"- \\($0.task)\" }.joined(separator: \"\\n\")"))
    }

    func testCompactActionsTabUsesMacStyleFilteredRows() throws {
        let source = try iosSource("WaiComputer/Features/Library/RecordingDetailView.swift")

        XCTAssertTrue(source.contains("struct RecordingDetailActionItemRow: View"))
        XCTAssertTrue(source.contains("RecordingDetailActionItemRow(item: item)"))
        XCTAssertTrue(source.contains("private var visibleActionItems: [ActionItem] {\n        visibleSummaryActionItems(actionItems)\n    }"))
        XCTAssertTrue(source.contains("ScrollView {\n                VStack(alignment: .leading, spacing: Spacing.lg)"))
        XCTAssertTrue(source.contains(".accessibilityIdentifier(\"recording-detail-actions-tab\")"))
        XCTAssertTrue(source.contains("section: \"actions-tab-action-items\""))
        XCTAssertFalse(source.contains("List(actionItems)"))
        XCTAssertFalse(source.contains("item.status == .completed ? .green : .gray"))
        XCTAssertFalse(source.contains("Image(systemName: item.status == .completed ? \"checkmark.circle.fill\" : \"circle\")"))
    }

    func testCompactSummaryTagsUseMacStylePills() throws {
        let source = try iosSource("WaiComputer/Features/Library/RecordingDetailView.swift")

        XCTAssertTrue(source.contains("summaryTagPill(topic)"))
        XCTAssertTrue(source.contains("summaryTagPill(person, systemImage: \"person.circle.fill\")"))
        XCTAssertTrue(source.contains("SectionView(title: t(\"People\", \"Люди\"))"))
        XCTAssertTrue(source.contains(".background(Palette.surfaceSubtle)"))
        XCTAssertTrue(source.contains(".clipShape(Capsule())"))
        XCTAssertFalse(source.contains(".background(Color.blue.opacity(0.1))"))
        XCTAssertFalse(source.contains(".background(Color.gray.opacity(0.1))"))
        XCTAssertFalse(source.contains(".cornerRadius(16)"))
    }

    func testRecordingViewHasRegularWidthMacStyleCaptureLayout() throws {
        let source = try iosSource("WaiComputer/Features/Recording/RecordingView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass)"))
        XCTAssertTrue(source.contains("regularRecordingLayout"))
        XCTAssertTrue(source.contains("recording-regular-layout"))
        XCTAssertTrue(source.contains("regularRecordingHeader"))
        XCTAssertTrue(source.contains("recording-regular-controls"))
        XCTAssertTrue(source.contains("compactRecordingLayout"))
    }

    func testCompactRecordingViewUsesMacStyleCaptureSurface() throws {
        let source = try iosSource("WaiComputer/Features/Recording/RecordingView.swift")

        XCTAssertTrue(source.contains("compactRecordingHero"))
        XCTAssertTrue(source.contains("compactRecordingStatusCard"))
        XCTAssertTrue(source.contains("recording-compact-controls"))
        XCTAssertTrue(source.contains("Typography.displaySmall"))
        XCTAssertTrue(source.contains("Typography.monoLarge"))
        XCTAssertTrue(source.contains("Palette.surfaceSubtle"))
        XCTAssertFalse(source.contains(".frame(width: 200, height: 200)"))
        XCTAssertFalse(source.contains(".font(.system(size: 48, weight: .light, design: .monospaced))"))
    }

    func testRecordingWarningsUseMacStyleInlineStatusBanner() throws {
        let source = try iosSource("WaiComputer/Features/Recording/RecordingView.swift")
        let bannerSource = try sourceSlice(
            source,
            startingAt: "private func warningBanner",
            endingBefore: "private func liveTranscriptPreview"
        )

        XCTAssertTrue(bannerSource.contains("Typography.headingSmall"))
        XCTAssertTrue(bannerSource.contains("Typography.caption"))
        XCTAssertTrue(bannerSource.contains("Palette.accent"))
        XCTAssertTrue(bannerSource.contains("Palette.accentSubtle"))
        XCTAssertTrue(bannerSource.contains("Palette.border"))
        XCTAssertTrue(bannerSource.contains("RoundedRectangle(cornerRadius: 14, style: .continuous)"))
        XCTAssertFalse(bannerSource.contains(".font(.subheadline.weight(.medium))"))
        XCTAssertFalse(bannerSource.contains(".font(.caption)"))
        XCTAssertFalse(bannerSource.contains(".background(Color.orange)"))
        XCTAssertFalse(bannerSource.contains(".padding(.horizontal)"))
    }

    func testRecordingRecoveryBannerUsesMacStyleStatusSurface() throws {
        let source = try iosSource("WaiComputer/App/ContentView.swift")
        let bannerSource = try sourceSlice(
            source,
            startingAt: "private struct RecordingRecoveryBanner",
            endingBefore: "#Preview"
        )

        XCTAssertTrue(bannerSource.contains("Typography.headingSmall"))
        XCTAssertTrue(bannerSource.contains("Typography.caption"))
        XCTAssertTrue(bannerSource.contains("Palette.accent"))
        XCTAssertTrue(bannerSource.contains("Palette.accentSubtle"))
        XCTAssertTrue(bannerSource.contains("Palette.border"))
        XCTAssertTrue(bannerSource.contains("RoundedRectangle(cornerRadius: 14, style: .continuous)"))
        XCTAssertFalse(bannerSource.contains(".foregroundStyle(.green)"))
        XCTAssertFalse(bannerSource.contains(".font(.headline)"))
        XCTAssertFalse(bannerSource.contains(".font(.subheadline)"))
        XCTAssertFalse(bannerSource.contains(".shadow(color: .black.opacity(0.12), radius: 10, y: 4)"))
    }

    func testSettingsViewHasRegularWidthMacStyleDashboardLayout() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass)"))
        XCTAssertTrue(source.contains("regularSettingsLayout"))
        XCTAssertTrue(source.contains("settings-regular-layout"))
        XCTAssertTrue(source.contains("regularSettingsPanel"))
        XCTAssertTrue(source.contains("settings-regular-recording-panel"))
        XCTAssertTrue(source.contains("settings-regular-integrations-panel"))
        XCTAssertTrue(source.contains("compactSettingsList"))
    }

    func testCompactSettingsAccountHeaderUsesMacStyleSurface() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")
        let headerSource = try sourceSlice(
            source,
            startingAt: "private func compactAccountHeader",
            endingBefore: "private var regularSettingsLayout"
        )

        XCTAssertTrue(source.contains("compactAccountHeader(user)"))
        XCTAssertTrue(headerSource.contains("settings-compact-account-header"))
        XCTAssertTrue(headerSource.contains("WaiTriangleIcon(size: 28)"))
        XCTAssertTrue(headerSource.contains("Typography.headingMedium"))
        XCTAssertTrue(headerSource.contains("Typography.caption"))
        XCTAssertTrue(headerSource.contains("Palette.surfaceSubtle"))
        XCTAssertTrue(headerSource.contains("Palette.border"))
        XCTAssertFalse(headerSource.contains(".font(.largeTitle)"))
        XCTAssertFalse(headerSource.contains(".font(.headline)"))
    }

    func testSettingsAboutPanelUsesIOSUpdateSemantics() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")

        XCTAssertTrue(source.contains("regularAboutPanel"))
        XCTAssertTrue(source.contains("settings-regular-about-panel"))
        XCTAssertTrue(source.contains("settings-regular-version-row"))
        XCTAssertTrue(source.contains("settings-regular-update-channel-row"))
        XCTAssertTrue(source.contains("updateChannelDescription"))
        XCTAssertTrue(source.contains("App Store or TestFlight"))
        XCTAssertTrue(source.contains("Automatic beta updates are managed in TestFlight"))
        XCTAssertFalse(source.contains("receiveBetaUpdates"))
        XCTAssertFalse(source.contains("waicomputerCheckForUpdates"))
        XCTAssertFalse(source.contains("Sparkle"))
    }

    func testIOSSettingsExposeAndHonorDictationLearnFromEditsPreference() throws {
        let settingsSource = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")
        let historySource = try iosSource("WaiComputer/Features/Dictation/DictationHistoryView.swift")
        let preferenceSource = try iosSource("WaiComputer/Features/Dictation/IOSDictationLearningSettings.swift")

        XCTAssertTrue(preferenceSource.contains("enabledDefaultsKey = \"dictationLearnFromEdits\""))
        XCTAssertTrue(settingsSource.contains("@AppStorage(IOSDictationLearningSettings.enabledDefaultsKey)"))
        XCTAssertTrue(settingsSource.contains("settings-dictation-learn-from-edits-toggle"))
        XCTAssertTrue(settingsSource.contains("Suggest words from my edits"))
        XCTAssertTrue(historySource.contains("@AppStorage(IOSDictationLearningSettings.enabledDefaultsKey)"))
        XCTAssertTrue(historySource.contains("if learnFromEditsEnabled {\n            learningEngine.observeEdit"))
    }

    func testSettingsRegularAccountPanelEmbedsReadOnlyBillingStatus() throws {
        let settingsSource = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")
        let billingSource = try iosSource("WaiComputer/Features/Billing/BillingStatusSection.swift")
        let appSource = try iosSource("WaiComputer/App/WaiComputerApp.swift")

        XCTAssertTrue(settingsSource.contains("BillingStatusPanel()"))
        XCTAssertTrue(billingSource.contains("struct BillingStatusPanel"))
        XCTAssertTrue(billingSource.contains("settings-regular-billing-summary"))
        XCTAssertTrue(billingSource.contains("BillingStatusBody(presentation: .listSectionRows)"))
        XCTAssertTrue(billingSource.contains("BillingStatusBody(presentation: .regularPanel)"))
        XCTAssertTrue(billingSource.contains("IOSTestingMode.current.isScreenshot"))
        XCTAssertTrue(appSource.contains("static let billingSubscription = BillingSubscription("))
        XCTAssertTrue(appSource.contains("static let billingUsage = BillingUsage("))
        XCTAssertFalse(billingSource.contains("createBillingCheckout"))
        XCTAssertFalse(billingSource.contains("settings-billing-upgrade"))
    }

    func testIOSWaiChatRoutesPreserveInitialChatId() throws {
        let contentSource = try iosSource("WaiComputer/App/ContentView.swift")
        let searchSource = try iosSource("WaiComputer/Features/Search/SearchView.swift")
        let waiSource = try iosSource("WaiComputer/Features/Wai/WaiHomeView.swift")
        let notificationSource = try iosSource("WaiComputer/Features/Wai/IOSWaiTaskNotificationCenter.swift")

        XCTAssertTrue(contentSource.contains("@State private var activeWaiChatId: String?"))
        XCTAssertTrue(contentSource.contains("notification.userInfo?[\"chatId\"] as? String"))
        XCTAssertTrue(contentSource.contains("WaiHomeView(initialChatId: activeWaiChatId)"))
        XCTAssertTrue(searchSource.contains("WaiHomeView(initialChatId: hit.parentId)"))
        XCTAssertTrue(waiSource.contains("let initialChatId: String?"))
        XCTAssertTrue(waiSource.contains("initialChatId: initialChatId"))
        XCTAssertTrue(notificationSource.contains("let chatId = response.notification.request.content.userInfo[\"chatId\"] as? String"))
        XCTAssertTrue(notificationSource.contains("userInfo: chatId.map { [\"chatId\": $0] }"))
    }

    func testIOSWaiCompanionUsesRegularWidthThreadSidebar() throws {
        let companionSource = try String(
            contentsOf: try repoRoot()
                .appendingPathComponent("shared/WaiComputerKit/Sources/WaiComputerKit/Views/CompanionView.swift"),
            encoding: .utf8
        )

        XCTAssertTrue(companionSource.contains("@Environment(\\.horizontalSizeClass) private var horizontalSizeClass"))
        XCTAssertTrue(companionSource.contains("regularIOSContent"))
        XCTAssertTrue(companionSource.contains("compactIOSContent"))
        XCTAssertTrue(companionSource.contains("horizontalSizeClass == .regular"))
        XCTAssertTrue(companionSource.contains("wai-regular-companion-layout"))
        XCTAssertTrue(companionSource.contains("wai-regular-thread-sidebar"))
        XCTAssertTrue(companionSource.contains("wai-compact-companion-layout"))
        XCTAssertTrue(companionSource.contains("chatList.frame(width: 280)"))
        XCTAssertTrue(companionSource.contains("compactThreadSheet"))
        XCTAssertTrue(companionSource.contains(".sheet(isPresented: $showChats)"))
        XCTAssertTrue(companionSource.contains(".presentationDetents([.medium, .large])"))
        XCTAssertFalse(companionSource.contains("chatList.frame(maxHeight: 220)"))
    }

    func testIOSWaiCompanionUsesConversationFirstCompactChatUX() throws {
        let companionSource = try String(
            contentsOf: try repoRoot()
                .appendingPathComponent("shared/WaiComputerKit/Sources/WaiComputerKit/Views/CompanionView.swift"),
            encoding: .utf8
        )
        let messageRowsSource = try sourceSlice(
            companionSource,
            startingAt: "private var messageRows: some View",
            endingBefore: "private var loadingState"
        )
        let composerSource = try sourceSlice(
            companionSource,
            startingAt: "private var composer: some View",
            endingBefore: "private func renameSheet"
        )

        XCTAssertTrue(companionSource.contains("Text(t(\"What can I help with?\", \"Чем помочь?\"))"))
        XCTAssertTrue(companionSource.contains("starterPromptButton(prompt)"))
        XCTAssertTrue(companionSource.contains("compactHeaderIconButton"))
        XCTAssertTrue(composerSource.contains("composerErrorBanner(message)"))
        XCTAssertTrue(composerSource.contains("Image(systemName: \"arrow.up\")"))
        XCTAssertTrue(composerSource.contains(".companionGlassChrome("))
        XCTAssertTrue(composerSource.contains("WaiDesignTokens.Radius.xl"))
        XCTAssertTrue(composerSource.contains(".companionGlassButton(tint: companionAccentColor, prominent: true)"))
        XCTAssertFalse(messageRowsSource.contains("Text(errorMessage)"))
        XCTAssertFalse(companionSource.contains(".font(.system(size: 22, weight: .semibold, design: .serif))"))
    }

    func testIOSSpeakerAssignmentUsesMacStylePickerSurface() throws {
        let source = try iosSource("WaiComputer/Features/Library/SpeakerChipButton.swift")

        XCTAssertTrue(source.contains("accessibilityIdentifier(\"speaker-chip-button\")"))
        XCTAssertTrue(source.contains("speakerAssignSearchField"))
        XCTAssertTrue(source.contains("accessibilityIdentifier(\"speaker-assign-search-field\")"))
        XCTAssertTrue(source.contains("speakerAssignErrorBanner"))
        XCTAssertTrue(source.contains("speakerPersonRow(person)"))
        XCTAssertTrue(source.contains("speakerCreateRow"))
        XCTAssertTrue(source.contains("Palette.accentSubtle"))
        XCTAssertTrue(source.contains("Palette.border"))
        XCTAssertTrue(source.contains("Typography.label"))
        XCTAssertFalse(source.contains(".textFieldStyle(.roundedBorder)"))
        XCTAssertFalse(source.contains(".foregroundStyle(.blue)"))
        XCTAssertFalse(source.contains("\"✨\\(conf)%\""))
    }

    func testAuthViewUsesMacStyleRegularLayout() throws {
        let source = try iosSource("WaiComputer/App/AuthView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var horizontalSizeClass"))
        XCTAssertTrue(source.contains("authContent"))
        XCTAssertTrue(source.contains("regularAuthLayout"))
        XCTAssertTrue(source.contains("compactAuthLayout"))
        XCTAssertTrue(source.contains("auth-regular-layout"))
        XCTAssertTrue(source.contains("auth-regular-brand-panel"))
        XCTAssertTrue(source.contains("auth-regular-form-panel"))
        XCTAssertTrue(source.contains("auth-compact-layout"))
        XCTAssertTrue(source.contains(".waiGlassButton(prominent: true)"))
        XCTAssertFalse(source.contains(".background(.blue)"))
    }

    func testOnboardingViewUsesMacStyleRegularLayout() throws {
        let source = try iosSource("WaiComputer/App/Onboarding/OnboardingView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var horizontalSizeClass"))
        XCTAssertTrue(source.contains("onboardingContent"))
        XCTAssertTrue(source.contains("regularOnboardingLayout"))
        XCTAssertTrue(source.contains("compactOnboardingLayout"))
        XCTAssertTrue(source.contains("onboarding-regular-layout"))
        XCTAssertTrue(source.contains("onboarding-regular-slide-panel"))
        XCTAssertTrue(source.contains("onboarding-regular-footer-panel"))
        XCTAssertTrue(source.contains("onboarding-compact-layout"))
        XCTAssertTrue(source.contains("pageIndicator(isRegular: true)"))
        XCTAssertTrue(source.contains("pageIndicator(isRegular: false)"))
        XCTAssertTrue(source.contains(".frame(maxWidth: 760)"))
        XCTAssertTrue(source.contains("ScrollView(.horizontal, showsIndicators: false)"))
        XCTAssertTrue(source.contains(".lineLimit(1)"))
    }

    func testIdentityAndVoiceSettingsUseMacStyleRegularLayoutAndFixtures() throws {
        let source = try iosSource("WaiComputer/Features/Settings/IdentityAndVoiceSettingsView.swift")
        let appSource = try iosSource("WaiComputer/App/WaiComputerApp.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass)"))
        XCTAssertTrue(source.contains("regularLayout"))
        XCTAssertTrue(source.contains("settings-identity-regular-layout"))
        XCTAssertTrue(source.contains("settings-identity-regular-header"))
        XCTAssertTrue(source.contains("settings-identity-regular-identity-panel"))
        XCTAssertTrue(source.contains("settings-identity-regular-voice-panel"))
        XCTAssertTrue(source.contains("settings-identity-first-name"))
        XCTAssertTrue(source.contains("settings-identity-last-name"))
        XCTAssertTrue(source.contains("settings-voice-sharing-toggle"))
        XCTAssertTrue(source.contains("IOSTestingMode.current.isScreenshot"))
        XCTAssertTrue(appSource.contains("static let identity = UserIdentity("))
        XCTAssertTrue(appSource.contains("static let voiceSharing = VoiceSharingState("))
        XCTAssertFalse(source.contains(".navigationTitle(\"Identity & Voice\")"))
        XCTAssertFalse(source.contains("Text(\"First name\")"))
    }

    func testMcpConnectSettingsUseMacStyleRegularLayout() throws {
        let source = try iosSource("WaiComputer/Features/Settings/McpConnectView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass)"))
        XCTAssertTrue(source.contains("regularLayout"))
        XCTAssertTrue(source.contains("compactForm"))
        XCTAssertTrue(source.contains("settings-mcp-regular-layout"))
        XCTAssertTrue(source.contains("settings-mcp-regular-header"))
        XCTAssertTrue(source.contains("settings-mcp-regular-endpoint-panel"))
        XCTAssertTrue(source.contains("settings-mcp-regular-guide-panel"))
        XCTAssertTrue(source.contains("settings-mcp-regular-access-panel"))
        XCTAssertTrue(source.contains("settings-mcp-copy-endpoint"))
        XCTAssertTrue(source.contains("settings-mcp-copy-snippet"))
        XCTAssertTrue(source.contains("settings-mcp-manage-tokens"))
    }

    func testTelegramSettingsUseMacStyleRegularLayoutAndFixtures() throws {
        let source = try iosSource("WaiComputer/Features/Settings/TelegramSettingsView.swift")
        let appSource = try iosSource("WaiComputer/App/WaiComputerApp.swift")
        let sharedSource = try String(
            contentsOf: try repoRoot()
                .appendingPathComponent("shared/WaiComputerKit/Sources/WaiComputerKit/Models/User.swift"),
            encoding: .utf8
        )

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass)"))
        XCTAssertTrue(source.contains("regularLayout"))
        XCTAssertTrue(source.contains("compactList"))
        XCTAssertTrue(source.contains("settings-telegram-regular-layout"))
        XCTAssertTrue(source.contains("settings-telegram-regular-header"))
        XCTAssertTrue(source.contains("settings-telegram-regular-status-panel"))
        XCTAssertTrue(source.contains("settings-telegram-regular-pairing-panel"))
        XCTAssertTrue(source.contains("settings-telegram-regular-capture-panel"))
        XCTAssertTrue(source.contains("IOSTestingMode.current.isScreenshot"))
        XCTAssertTrue(source.contains("telegramStatus = IOSScreenshotFixtures.telegramStatus"))
        XCTAssertTrue(appSource.contains("static let telegramStatus = TelegramLinkStatus("))
        XCTAssertTrue(sharedSource.contains("public init(\n        linked: Bool"))
    }

    func testSettingsDataScreensUseRealServerDataMapInsteadOfPlaceholders() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")

        XCTAssertTrue(source.contains("ServerDataView"))
        XCTAssertTrue(source.contains("ExportReadinessView"))
        XCTAssertTrue(source.contains("getSystemInfo()"))
        XCTAssertTrue(source.contains("getDataOwnershipMap()"))
        XCTAssertTrue(source.contains("settings-server-data-view"))
        XCTAssertTrue(source.contains("settings-export-readiness-view"))
        XCTAssertFalse(source.contains("125 MB"))
        XCTAssertFalse(source.contains("2.3 GB"))
        XCTAssertFalse(source.contains("Button(\"Export All Transcripts (TXT)\") {}"))
        XCTAssertFalse(source.contains("Button(\"Export All Audio (ZIP)\") {}"))
    }

    func testSettingsRecordingPipelineReplacesDeadAudioControls() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")

        XCTAssertTrue(source.contains("RecordingPipelineView"))
        XCTAssertTrue(source.contains("settings-recording-pipeline-view"))
        XCTAssertTrue(source.contains("getTranscriptionOptions()"))
        XCTAssertTrue(source.contains("AudioCaptureConfig.default.sampleRate"))
        XCTAssertFalse(source.contains("AudioSettingsView"))
        XCTAssertFalse(source.contains("@AppStorage(\"audioSampleRate\")"))
        XCTAssertFalse(source.contains("@AppStorage(\"enableNoiseSuppression\")"))
        XCTAssertFalse(source.contains("Toggle(\"Noise Suppression\""))
    }

    func testRecordingPipelineSettingsUseMacStyleRegularLayoutAndFixtures() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var pipelineHorizontalSizeClass"))
        XCTAssertTrue(source.contains("recordingPipelineRegularLayout"))
        XCTAssertTrue(source.contains("recordingPipelineCompactList"))
        XCTAssertTrue(source.contains("settings-recording-pipeline-regular-layout"))
        XCTAssertTrue(source.contains("settings-recording-pipeline-regular-header"))
        XCTAssertTrue(source.contains("settings-recording-pipeline-regular-capture-panel"))
        XCTAssertTrue(source.contains("settings-recording-pipeline-regular-server-panel"))
        XCTAssertTrue(source.contains("settings-recording-pipeline-regular-dictation-panel"))
        XCTAssertTrue(source.contains("IOSRecordingPipelineFixtures.snapshot"))
        XCTAssertTrue(source.contains(".navigationBarTitleDisplayMode(pipelineHorizontalSizeClass == .regular ? .inline : .large)"))
    }

    func testTranscriptionLanguageSettingsUseMacStyleRegularLayout() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")

        XCTAssertTrue(source.contains("dictationLanguageRegularLayout"))
        XCTAssertTrue(source.contains("dictationLanguageCompactForm"))
        XCTAssertTrue(source.contains("settings-transcription-language-regular-layout"))
        XCTAssertTrue(source.contains("settings-transcription-language-regular-header"))
        XCTAssertTrue(source.contains("settings-transcription-language-picker-panel"))
        XCTAssertTrue(source.contains("settings-transcription-language-summary-panel"))
        XCTAssertTrue(source.contains("LanguagePickerView(store: dictationLanguageStore)"))
        XCTAssertTrue(source.contains(".navigationBarTitleDisplayMode(horizontalSizeClass == .regular ? .inline : .large)"))
    }

    func testSummarySettingsSurfaceLoadAndSaveErrors() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")

        XCTAssertTrue(source.contains("settings-summary-view"))
        XCTAssertTrue(source.contains("Couldn't load summary settings"))
        XCTAssertTrue(source.contains("Couldn't save summary settings"))
        XCTAssertTrue(source.contains("guard settingsLoaded else { return }"))
        XCTAssertFalse(source.contains("@AppStorage(\"autoSummarize\")"))
        XCTAssertFalse(source.contains("Toggle(\"Auto-summarize recordings\""))
        XCTAssertFalse(source.contains("catch {\n            // Use defaults"))
        XCTAssertFalse(source.contains("_ = try? await appState.getAPIClient().updateSettings(request)"))
    }

    func testSummarySettingsUseMacStyleRegularLayoutAndFixtures() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")

        XCTAssertTrue(source.contains("summaryRegularLayout"))
        XCTAssertTrue(source.contains("summaryCompactList"))
        XCTAssertTrue(source.contains("settings-summary-regular-layout"))
        XCTAssertTrue(source.contains("settings-summary-regular-header"))
        XCTAssertTrue(source.contains("settings-summary-regular-defaults-panel"))
        XCTAssertTrue(source.contains("settings-summary-regular-instructions-panel"))
        XCTAssertTrue(source.contains("settings-summary-regular-preview-panel"))
        XCTAssertTrue(source.contains("settings-summary-instructions-editor"))
        XCTAssertTrue(source.contains("IOSSummarySettingsFixtures.settings"))
        XCTAssertTrue(source.contains("if IOSTestingMode.current.isScreenshot"))
        XCTAssertTrue(source.contains("if IOSTestingMode.current.isScreenshot {\n            settingsError = nil\n            return"))
        XCTAssertTrue(source.contains(".navigationBarTitleDisplayMode(summaryHorizontalSizeClass == .regular ? .inline : .large)"))
    }

    func testAppearanceSettingsUseMacStyleRegularLayout() throws {
        let source = try iosSource("WaiComputer/Features/Settings/AppearanceSettingsView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var appearanceHorizontalSizeClass"))
        XCTAssertTrue(source.contains("appearanceRegularLayout"))
        XCTAssertTrue(source.contains("appearanceCompactList"))
        XCTAssertTrue(source.contains("settings-appearance-regular-layout"))
        XCTAssertTrue(source.contains("settings-appearance-regular-header"))
        XCTAssertTrue(source.contains("settings-appearance-regular-theme-panel"))
        XCTAssertTrue(source.contains("settings-appearance-regular-accent-panel"))
        XCTAssertTrue(source.contains("settings-appearance-regular-preview-panel"))
        XCTAssertTrue(source.contains("LazyVGrid("))
        XCTAssertTrue(source.contains(".navigationBarTitleDisplayMode(appearanceHorizontalSizeClass == .regular ? .inline : .large)"))
    }

    func testServerDataSettingsUseMacStyleRegularLayoutAndFixtures() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var serverDataHorizontalSizeClass"))
        XCTAssertTrue(source.contains("serverDataRegularLayout"))
        XCTAssertTrue(source.contains("serverDataCompactList"))
        XCTAssertTrue(source.contains("settings-server-data-regular-layout"))
        XCTAssertTrue(source.contains("settings-server-data-regular-header"))
        XCTAssertTrue(source.contains("settings-server-data-regular-overview-panel"))
        XCTAssertTrue(source.contains("settings-server-data-regular-owned-panel"))
        XCTAssertTrue(source.contains("settings-server-data-regular-files-panel"))
        XCTAssertTrue(source.contains("IOSServerDataFixtures.snapshot"))
        XCTAssertTrue(source.contains(".navigationBarTitleDisplayMode(serverDataHorizontalSizeClass == .regular ? .inline : .large)"))
    }

    func testExportReadinessSettingsUseMacStyleRegularLayoutAndFixtures() throws {
        let source = try iosSource("WaiComputer/Features/Settings/SettingsView.swift")

        XCTAssertTrue(source.contains("@Environment(\\.horizontalSizeClass) private var exportHorizontalSizeClass"))
        XCTAssertTrue(source.contains("exportRegularLayout"))
        XCTAssertTrue(source.contains("exportCompactList"))
        XCTAssertTrue(source.contains("settings-export-readiness-regular-layout"))
        XCTAssertTrue(source.contains("settings-export-readiness-regular-header"))
        XCTAssertTrue(source.contains("settings-export-readiness-regular-summary-panel"))
        XCTAssertTrue(source.contains("settings-export-readiness-regular-exportable-panel"))
        XCTAssertTrue(source.contains("settings-export-readiness-regular-reconnect-panel"))
        XCTAssertTrue(source.contains("settings-export-readiness-regular-excluded-panel"))
        XCTAssertTrue(source.contains("IOSServerDataFixtures.snapshot"))
        XCTAssertTrue(source.contains(".navigationBarTitleDisplayMode(exportHorizontalSizeClass == .regular ? .inline : .large)"))
    }

    // MARK: - Live transcript performance (append-only builder + chunked rendering)

    func testCommittedLiveTranscriptBuilderMatchesLegacyRebuildAcrossEventSequences() {
        let displaySpeaker: (String) -> String = { raw in
            raw == "Speaker" ? "Speaker" : "SPK<\(raw)>"
        }

        enum Event {
            case append(speaker: String?, text: String)
            case replace(speaker: String?, text: String)
        }

        // Covers: plain lines, nil→"Speaker" grouping, literal "Speaker"
        // merging with nil-speaker lines, same-speaker runs, speaker switches,
        // replacement corrections, and whitespace-only labels (grouped by raw
        // value but never counted as a visible speaker).
        let events: [Event] = [
            .append(speaker: nil, text: "hello"),
            .append(speaker: nil, text: "world"),
            .append(speaker: "speaker_0", text: "first"),
            .append(speaker: "speaker_0", text: "second"),
            .replace(speaker: "speaker_0", text: "second, corrected"),
            .append(speaker: "speaker_1", text: "third"),
            .append(speaker: "Speaker", text: "fourth"),
            .append(speaker: nil, text: "fifth"),
            .replace(speaker: nil, text: "fifth, fixed"),
            .append(speaker: "  ", text: "sixth"),
            .append(speaker: "speaker_0", text: "seventh"),
        ]

        var builder = CommittedLiveTranscriptBuilder()
        var legacyLines: [(speaker: String?, text: String)] = []

        for (index, event) in events.enumerated() {
            switch event {
            case .append(let speaker, let text):
                builder.append(
                    speaker: speaker, text: text,
                    languageKey: "en", displaySpeaker: displaySpeaker
                )
                legacyLines.append((speaker, text))
            case .replace(let speaker, let text):
                builder.replaceLast(
                    speaker: speaker, text: text,
                    languageKey: "en", displaySpeaker: displaySpeaker
                )
                if legacyLines.isEmpty {
                    legacyLines.append((speaker, text))
                } else {
                    legacyLines[legacyLines.count - 1] = (speaker, text)
                }
            }

            // The builder must match the legacy full rebuild byte-for-byte in
            // both formats after every event, so the format can flip at any
            // moment (first speaker label may arrive via an interim).
            XCTAssertEqual(
                builder.committedText(showsSpeakers: false, languageKey: "en", displaySpeaker: displaySpeaker),
                legacyCommittedText(lines: legacyLines, showsSpeakers: false, displaySpeaker: displaySpeaker),
                "plain text diverged after event #\(index)"
            )
            XCTAssertEqual(
                builder.committedText(showsSpeakers: true, languageKey: "en", displaySpeaker: displaySpeaker),
                legacyCommittedText(lines: legacyLines, showsSpeakers: true, displaySpeaker: displaySpeaker),
                "speaker text diverged after event #\(index)"
            )
            XCTAssertEqual(
                builder.hasSpeakerLabel,
                legacyLines.contains { speaker, _ in
                    guard let speaker else { return false }
                    return !speaker.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                },
                "speaker-label flag diverged after event #\(index)"
            )
            XCTAssertEqual(builder.lastLineSpeaker, legacyLines.last?.speaker)
        }
    }

    func testCommittedLiveTranscriptBuilderRebuildsSpeakerLabelsOnLanguageChange() {
        let english: (String) -> String = { _ in "Speaker 1" }
        let russian: (String) -> String = { _ in "Говорящий 1" }

        var builder = CommittedLiveTranscriptBuilder()
        builder.append(speaker: "speaker_0", text: "привет", languageKey: "en", displaySpeaker: english)
        builder.append(speaker: "speaker_0", text: "мир", languageKey: "en", displaySpeaker: english)

        XCTAssertEqual(
            builder.committedText(showsSpeakers: true, languageKey: "en", displaySpeaker: english),
            "Speaker 1: привет мир"
        )
        // Switching the language key re-renders already-committed labels.
        XCTAssertEqual(
            builder.committedText(showsSpeakers: true, languageKey: "ru", displaySpeaker: russian),
            "Говорящий 1: привет мир"
        )
    }

    func testCommittedLiveTranscriptBuilderReplaceOnEmptyAppendsLikeLegacyHandler() {
        var builder = CommittedLiveTranscriptBuilder()
        builder.replaceLast(speaker: nil, text: "only line", languageKey: "en", displaySpeaker: { $0 })

        XCTAssertEqual(
            builder.committedText(showsSpeakers: false, languageKey: "en", displaySpeaker: { $0 }),
            "only line"
        )
        XCTAssertEqual(builder.lines.count, 1)
    }

    func testLiveTranscriptChunkCacheExtendsLastChunkForAppendOnlyGrowth() {
        let cache = LiveTranscriptChunkCache()

        XCTAssertTrue(cache.chunks(for: "").isEmpty)

        let first = cache.chunks(for: "Hello")
        XCTAssertEqual(first.map(\.text), ["Hello"])

        let grown = cache.chunks(for: "Hello world")
        XCTAssertEqual(grown.map(\.text), ["Hello world"])
        XCTAssertEqual(grown.map(\.id), first.map(\.id), "append-only growth must keep chunk identity stable")

        // Once the last chunk crosses the size cap, the next delta opens a new
        // row (with its separator trimmed) instead of growing the old one.
        let long = "Hello world " + String(repeating: "a", count: 1_300)
        let capped = cache.chunks(for: long)
        XCTAssertEqual(capped.count, 1)

        let overflow = cache.chunks(for: long + " tail words")
        XCTAssertEqual(overflow.count, 2)
        XCTAssertEqual(overflow.last?.text, "tail words")
        XCTAssertEqual(overflow.first?.text, long)
    }

    func testLiveTranscriptChunkCacheRebuildsOnRewriteAndResetsOnEmpty() {
        let cache = LiveTranscriptChunkCache()
        _ = cache.chunks(for: "Original committed text")

        // Replacement events rewrite the tail — not append-only — so the
        // cache must rebuild rather than append.
        let rewritten = cache.chunks(for: "Original committed rewrite")
        XCTAssertEqual(rewritten.map(\.text), ["Original committed rewrite"])

        // A long transcript rebuild splits at word boundaries within the cap.
        let words = Array(repeating: "transcript", count: 400).joined(separator: " ")
        let chunks = cache.chunks(for: words)
        XCTAssertGreaterThan(chunks.count, 1)
        XCTAssertTrue(chunks.allSatisfy { $0.text.count <= 1_200 })
        XCTAssertEqual(chunks.map(\.text).joined(separator: " "), words)

        // Clearing the transcript (new recording) resets identity.
        XCTAssertTrue(cache.chunks(for: "").isEmpty)
        XCTAssertEqual(cache.chunks(for: "fresh").first?.id, 0)
    }

    @MainActor
    func testRecordingDetailViewModelMemoizesTranscriptTurnsAndInvalidatesOnDetailChange() {
        let segments = [
            Segment(id: "s1", speaker: "Speaker 1", rawLabel: "speaker_1", content: "Hello there.", startMs: 0, endMs: 1_000),
            Segment(id: "s2", speaker: "Speaker 1", rawLabel: "speaker_1", content: "How are you?", startMs: 1_000, endMs: 2_000),
            Segment(id: "s3", speaker: "Speaker 2", rawLabel: "speaker_2", content: "I am well.", startMs: 2_000, endMs: 3_000),
        ]
        let viewModel = RecordingDetailViewModel()
        viewModel.detail = RecordingDetail(
            id: "rec-memo",
            title: "Memo",
            type: .meeting,
            status: .ready,
            createdAt: Date(timeIntervalSince1970: 1_709_292_000),
            segments: segments
        )

        // Consecutive same-speaker utterances merge into one turn → 2 turns.
        let first = viewModel.transcriptTurns(languageCode: "en")
        XCTAssertEqual(first.count, 2)
        XCTAssertEqual(first.first?.text, "Hello there. How are you?")

        // Repeated call (the memoized per-body path) returns identical turns.
        let second = viewModel.transcriptTurns(languageCode: "en")
        XCTAssertEqual(second.map(\.id), first.map(\.id))
        XCTAssertEqual(second.map(\.text), first.map(\.text))

        // Reassigning every utterance to one person must invalidate the cache
        // and regroup into a single turn.
        let reassigned = segments.map { segment in
            Segment(
                id: segment.id,
                speaker: segment.speaker,
                rawLabel: segment.rawLabel,
                personId: "person-1",
                content: segment.content,
                startMs: segment.startMs,
                endMs: segment.endMs
            )
        }
        viewModel.detail = RecordingDetail(
            id: "rec-memo",
            title: "Memo",
            type: .meeting,
            status: .ready,
            createdAt: Date(timeIntervalSince1970: 1_709_292_000),
            segments: reassigned
        )

        let afterReassign = viewModel.transcriptTurns(languageCode: "en")
        XCTAssertEqual(afterReassign.count, 1, "cache must invalidate when speaker assignments change")
        XCTAssertEqual(afterReassign.first?.text, "Hello there. How are you? I am well.")

        // Language changes recompute for the new locale.
        XCTAssertEqual(viewModel.transcriptTurns(languageCode: "ru").count, 1)
    }

    func testLiveRecordingRendersCommittedTranscriptAsChunkedRows() throws {
        let viewSource = try iosSource("WaiComputer/Features/Recording/RecordingView.swift")

        XCTAssertTrue(viewSource.contains("@State private var committedChunkCache = LiveTranscriptChunkCache()"))
        XCTAssertTrue(viewSource.contains("let committedChunks = committedChunkCache.chunks(for: viewModel.committedTranscript)"))
        XCTAssertTrue(viewSource.contains("ForEach(committedChunks)"))
        // One ever-growing Text forced SwiftUI to re-lay-out the entire
        // committed transcript on every realtime delta.
        XCTAssertFalse(viewSource.contains("Text(viewModel.committedTranscript)"))
        // Animated auto-scroll only on committed growth; interim ticks follow
        // without animation.
        XCTAssertTrue(viewSource.contains(".onChange(of: viewModel.committedTranscript)"))
        XCTAssertTrue(viewSource.contains(".onChange(of: viewModel.interimTranscript)"))
        XCTAssertFalse(viewSource.contains(".onChange(of: viewModel.currentTranscript)"))
    }

    func testLiveRecordingViewModelAppendsCommittedTextAndCoalescesInterimPublishes() throws {
        let modelSource = try iosSource("WaiComputer/Features/Recording/RecordingViewModel.swift")

        XCTAssertTrue(modelSource.contains("private var committedBuilder = CommittedLiveTranscriptBuilder()"))
        XCTAssertTrue(modelSource.contains("private static let interimPublishInterval: Duration = .milliseconds(100)"))
        XCTAssertTrue(modelSource.contains("publishLiveTranscript(coalescing: true)"))
        XCTAssertTrue(modelSource.contains("publishLiveTranscript(coalescing: false)"))
        // Coalesced interim state must be flushed before segments finalize.
        XCTAssertTrue(modelSource.contains("self.flushPendingLiveTranscript()"))
        // The per-event full rebuilds must not come back.
        XCTAssertFalse(modelSource.contains("committedTranscript = buildCommittedTranscriptText()"))
        XCTAssertFalse(modelSource.contains("currentTranscript = buildTranscriptText()"))
    }

    func testTranscriptDetailSurfacesMemoizeMergedTurns() throws {
        let transcriptSource = try iosSource("WaiComputer/Features/Library/TranscriptView.swift")
        let detailViewSource = try iosSource("WaiComputer/Features/Library/RecordingDetailView.swift")
        let detailModelSource = try iosSource("WaiComputer/Features/Library/RecordingDetailViewModel.swift")

        XCTAssertTrue(transcriptSource.contains("@State private var displayCache = TranscriptDisplayCache()"))
        XCTAssertTrue(transcriptSource.contains("ForEach(displayCache.turns(for: segments, languageCode: speakerLanguageCode))"))
        XCTAssertFalse(transcriptSource.contains("ForEach(TranscriptRendering.mergeTurns("))
        XCTAssertTrue(detailViewSource.contains("ForEach(viewModel.transcriptTurns(languageCode: speakerLanguageCode))"))
        XCTAssertFalse(detailViewSource.contains("ForEach(TranscriptRendering.mergeTurns("))
        XCTAssertTrue(detailModelSource.contains("didSet { detailRevision += 1 }"))
        XCTAssertTrue(detailModelSource.contains("TranscriptTurnsCacheKey(languageCode: languageCode, revision: detailRevision)"))
    }

    /// Reference implementation of the pre-optimization full rebuild, kept in
    /// the tests as the semantic contract for `CommittedLiveTranscriptBuilder`.
    private func legacyCommittedText(
        lines: [(speaker: String?, text: String)],
        showsSpeakers: Bool,
        displaySpeaker: (String) -> String
    ) -> String {
        guard showsSpeakers else {
            return lines.map(\.text).joined(separator: " ")
        }
        var parts: [String] = []
        var currentSpeaker: String?
        var currentText = ""
        for line in lines {
            let speaker = line.speaker ?? "Speaker"
            if speaker == currentSpeaker {
                currentText += " " + line.text
            } else {
                if !currentText.isEmpty, let s = currentSpeaker {
                    parts.append("\(displaySpeaker(s)): \(currentText)")
                }
                currentSpeaker = speaker
                currentText = line.text
            }
        }
        if !currentText.isEmpty, let s = currentSpeaker {
            parts.append("\(displaySpeaker(s)): \(currentText)")
        }
        return parts.joined(separator: "\n\n")
    }

    private func XCTAssertImportTypes(
        _ types: [UTType],
        includeExtension ext: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        guard let expected = UTType(filenameExtension: ext) else {
            XCTFail("Expected UTType for .\(ext)", file: file, line: line)
            return
        }
        XCTAssertTrue(
            types.contains { $0 == expected || $0.conforms(to: expected) || expected.conforms(to: $0) },
            "Expected import types to include .\(ext)",
            file: file,
            line: line
        )
    }

    private func iosSource(_ relativePath: String) throws -> String {
        let file = try repoRoot()
            .appendingPathComponent("ios/WaiComputer")
            .appendingPathComponent(relativePath)
        return try String(contentsOf: file, encoding: .utf8)
    }

    private func sourceSlice(_ source: String, startingAt start: String, endingBefore end: String) throws -> String {
        guard let startRange = source.range(of: start) else {
            XCTFail("Missing source slice start: \(start)")
            return source
        }
        guard let endRange = source[startRange.lowerBound...].range(of: end) else {
            XCTFail("Missing source slice end: \(end)")
            return String(source[startRange.lowerBound...])
        }
        return String(source[startRange.lowerBound..<endRange.lowerBound])
    }

    private func repoRoot() throws -> URL {
        let candidates = [
            URL(fileURLWithPath: #filePath),
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath),
        ]

        for candidate in candidates {
            var directory = candidate.hasDirectoryPath ? candidate : candidate.deletingLastPathComponent()
            while directory.path != directory.deletingLastPathComponent().path {
                let marker = directory.appendingPathComponent("scripts/capture-ios-appstore-screenshots.sh")
                if FileManager.default.fileExists(atPath: marker.path) {
                    return directory
                }
                directory.deleteLastPathComponent()
            }
        }

        throw XCTSkip("Unable to locate wai-computer repo root from test runtime")
    }
}
