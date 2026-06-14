import XCTest
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
}
