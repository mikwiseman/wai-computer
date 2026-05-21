import AppKit
import XCTest

final class DictationOverlayPanelTests: XCTestCase {
    @MainActor
    func testOverlayPanelStaysAboveFullscreenWorkspacesWithoutTakingFocus() {
        let panel = DictationOverlayPanel()

        XCTAssertEqual(panel.level, .statusBar)
        XCTAssertTrue(panel.collectionBehavior.contains(.canJoinAllSpaces))
        XCTAssertTrue(panel.collectionBehavior.contains(.fullScreenAuxiliary))
        XCTAssertTrue(panel.collectionBehavior.contains(.stationary))
        XCTAssertFalse(panel.hidesOnDeactivate)
        XCTAssertFalse(panel.canBecomeKey)
        XCTAssertFalse(panel.canBecomeMain)
        XCTAssertFalse(panel.isReleasedWhenClosed)
        XCTAssertEqual(panel.accessibilityIdentifier(), "dictation-overlay-panel")
    }
}
