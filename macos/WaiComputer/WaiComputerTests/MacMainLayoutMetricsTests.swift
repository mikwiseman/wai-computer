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
        XCTAssertGreaterThanOrEqual(MacMainLayoutMetrics.searchContentMaxWidth, 800)
    }
}
