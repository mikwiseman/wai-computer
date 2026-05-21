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

    func testHeaderIndicatorDoesNotCallSystemAudioSetupAMicrophoneWarning() {
        XCTAssertEqual(
            SystemAudioWarningPolicy.headerIndicator(
                requestedSystemAudio: true,
                hasSystemAudio: false,
                warning: nil
            ),
            .systemAudioStarting
        )
    }

    func testHeaderIndicatorDistinguishesDegradedSystemAudioFromMicrophonePermission() {
        XCTAssertEqual(
            SystemAudioWarningPolicy.headerIndicator(
                requestedSystemAudio: true,
                hasSystemAudio: true,
                warning: "system audio stalled"
            ),
            .systemAudioDegraded
        )
    }

    func testSystemAudioReadinessNeverReportsReadyWhenUnsupported() {
        XCTAssertEqual(
            SystemAudioReadinessPolicy.status(
                isSupported: false,
                preflightPassedInCurrentProcess: true,
                openedSettingsDuringCurrentAttempt: false
            ),
            .unsupported
        )
    }

    func testSystemAudioReadinessRequiresCurrentProcessPreflight() {
        XCTAssertEqual(
            SystemAudioReadinessPolicy.status(
                isSupported: true,
                preflightPassedInCurrentProcess: false,
                openedSettingsDuringCurrentAttempt: false
            ),
            .setupNeeded
        )

        XCTAssertEqual(
            SystemAudioReadinessPolicy.status(
                isSupported: true,
                preflightPassedInCurrentProcess: true,
                openedSettingsDuringCurrentAttempt: false
            ),
            .ready
        )
    }

    func testSystemAudioReadinessMarksSettingsRoundTripAsRestartRequired() {
        XCTAssertEqual(
            SystemAudioReadinessPolicy.status(
                isSupported: true,
                preflightPassedInCurrentProcess: false,
                openedSettingsDuringCurrentAttempt: true
            ),
            .restartRequired
        )
    }

    func testSandboxFinalTranscriptAppendsWhenTextInserterDidNotChangeField() {
        XCTAssertEqual(
            OnboardingDictationSandboxPolicy.textAfterFinalTranscript(
                currentText: "Draft",
                textBeforeUtterance: "Draft",
                finalTranscript: "hello world"
            ),
            "Draft hello world"
        )
    }

    func testSandboxFinalTranscriptSkipsWhenTextInserterAlreadyInsertedIntoFocusedField() {
        XCTAssertEqual(
            OnboardingDictationSandboxPolicy.textAfterFinalTranscript(
                currentText: "Draft hello world",
                textBeforeUtterance: "Draft",
                finalTranscript: "hello world"
            ),
            "Draft hello world"
        )
    }

    func testSandboxFinalTranscriptStillAllowsRepeatedUtteranceWhenFieldDidNotChange() {
        XCTAssertEqual(
            OnboardingDictationSandboxPolicy.textAfterFinalTranscript(
                currentText: "hello world",
                textBeforeUtterance: "hello world",
                finalTranscript: "hello world"
            ),
            "hello world hello world"
        )
    }
}
