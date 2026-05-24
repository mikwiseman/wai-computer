import XCTest

final class MacMainLayoutMetricsTests: XCTestCase {
    func testSidebarLeavesRoomForNativeChromeOnLaptopWidths() {
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.sidebarMinWidth, 236)
        XCTAssertGreaterThan(MacMainLayoutMetrics.sidebarIdealWidth, MacMainLayoutMetrics.sidebarMinWidth)
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.sidebarMaxWidth, MacMainLayoutMetrics.sidebarIdealWidth)
    }

    func testListColumnKeepsRecordingRowsReadable() {
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.listMinWidth, 360)
        XCTAssertGreaterThan(MacMainLayoutMetrics.listIdealWidth, MacMainLayoutMetrics.listMinWidth)
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.listMaxWidth, MacMainLayoutMetrics.listIdealWidth)
    }

    func testToolbarAndRenameSheetUseStableDimensions() {
        XCTAssertEqual(MacMainLayoutMetrics.toolbarIconFrame, 28)
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.folderNameSheetWidth, 600)
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.folderNameSheetActionWidth, 168)
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.recordingTitleEditMinWidth, 420)
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.searchContentMaxWidth, 800)
    }

    func testSpeakerAssignmentPopoverStaysWithinReadableDetailColumn() {
        XCTAssertLessThanOrEqual(
            MacMainLayoutMetrics.speakerAssignmentPopoverWidth,
            MacMainLayoutMetrics.minimumReadableDetailWidth
        )
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.speakerAssignmentPopoverWidth, 320)
    }

    func testSidebarRowsHaveStableFullWidthHitTargets() {
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.sidebarRowMinHeight, 28)
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.sidebarRowHorizontalPadding, 8)
    }

    func testListSectionsHideSidebarBeforeDetailBecomesUnreadable() {
        let narrowWidth = MacMainLayoutMetrics.allColumnsReadableWidth - 1
        let wideWidth = MacMainLayoutMetrics.allColumnsReadableWidth + 1

        XCTAssertEqual(
            MacMainLayoutMetrics.preferredColumnVisibility(
                hasListColumn: true,
                containerWidth: narrowWidth
            ),
            .doubleColumn
        )
        XCTAssertEqual(
            MacMainLayoutMetrics.preferredColumnVisibility(
                hasListColumn: true,
                containerWidth: wideWidth
            ),
            .all
        )
        XCTAssertEqual(
            MacMainLayoutMetrics.preferredColumnVisibility(
                hasListColumn: false,
                containerWidth: narrowWidth
            ),
            .all
        )
    }
}
