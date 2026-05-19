import XCTest

final class SystemAudioWarningPolicyTests: XCTestCase {
    func testDoesNotShowCaptureWarningBeforeStallDetectorFires() {
        XCTAssertFalse(
            SystemAudioWarningPolicy.shouldShowCaptureWarning(
                systemAudioStalled: false,
                systemAudioReceivedAny: false
            ),
            "A fresh system-audio stream can be silent before the stall detector has made a decision."
        )
    }

    func testShowsCaptureWarningAfterStallDetectorFires() {
        XCTAssertTrue(
            SystemAudioWarningPolicy.shouldShowCaptureWarning(
                systemAudioStalled: true,
                systemAudioReceivedAny: false
            )
        )
    }

    func testDoesNotShowCaptureWarningWhileSystemAudioIsHealthy() {
        XCTAssertFalse(
            SystemAudioWarningPolicy.shouldShowCaptureWarning(
                systemAudioStalled: false,
                systemAudioReceivedAny: true
            )
        )
    }
}
