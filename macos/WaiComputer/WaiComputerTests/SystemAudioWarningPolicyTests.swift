import XCTest
import WaiComputerKit

final class SystemAudioWarningPolicyTests: XCTestCase {
    private let warning = "System audio is not reaching WaiComputer. Microphone audio is still being recorded."

    func testShowsSystemAudioBannerForNoteWhenSystemAudioWasRequested() {
        XCTAssertEqual(
            SystemAudioWarningPolicy.visibleBannerText(
                recordingType: .note,
                requestedSystemAudio: true,
                warning: warning
            ),
            warning,
            "If the user opted into dual capture, the warning must fire even for note recordings."
        )
    }

    func testShowsSystemAudioBannerForReflectionWhenSystemAudioWasRequested() {
        XCTAssertEqual(
            SystemAudioWarningPolicy.visibleBannerText(
                recordingType: .reflection,
                requestedSystemAudio: true,
                warning: warning
            ),
            warning
        )
    }

    func testShowsSystemAudioBannerForMeetingWhenSystemAudioWasRequested() {
        XCTAssertEqual(
            SystemAudioWarningPolicy.visibleBannerText(
                recordingType: .meeting,
                requestedSystemAudio: true,
                warning: warning
            ),
            warning
        )
    }

    func testHidesSystemAudioBannerWhenSystemAudioWasNotRequested() {
        XCTAssertNil(
            SystemAudioWarningPolicy.visibleBannerText(
                recordingType: .meeting,
                requestedSystemAudio: false,
                warning: warning
            )
        )
    }

    func testHidesEmptyWarnings() {
        XCTAssertNil(
            SystemAudioWarningPolicy.visibleBannerText(
                recordingType: .meeting,
                requestedSystemAudio: true,
                warning: " "
            )
        )
    }

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
