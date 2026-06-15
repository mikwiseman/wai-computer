import XCTest

extension XCTestCase {
    func requireForegroundXCUITestOptIn() throws {
        guard ProcessInfo.processInfo.environment["WAI_ALLOW_FOREGROUND_XCUITESTS"] == "1" else {
            throw XCTSkip(
                """
                macOS XCUITests launch and activate WaiComputer. Use scripts/macos-peekaboo-smoke.sh \
                for the background/offscreen smoke gate, or set WAI_ALLOW_FOREGROUND_XCUITESTS=1 \
                only for explicit foreground local diagnosis.
                """
            )
        }
    }
}
