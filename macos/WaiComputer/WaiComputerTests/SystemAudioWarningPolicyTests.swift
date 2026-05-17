import XCTest
import WaiComputerKit

final class SystemAudioWarningPolicyTests: XCTestCase {
    private let warning = "System audio is not reaching WaiComputer. Microphone audio is still being recorded."

    func testHidesSystemAudioBannerForSoloNote() {
        XCTAssertNil(
            SystemAudioWarningPolicy.visibleBannerText(
                recordingType: .note,
                requestedSystemAudio: true,
                warning: warning
            )
        )
    }

    func testHidesSystemAudioBannerForReflection() {
        XCTAssertNil(
            SystemAudioWarningPolicy.visibleBannerText(
                recordingType: .reflection,
                requestedSystemAudio: true,
                warning: warning
            )
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
}
