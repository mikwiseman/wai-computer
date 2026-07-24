import XCTest
import AVFoundation
@testable import WaiComputerKit

final class SystemAudioWarningPolicyTests: XCTestCase {
    func testOnboardingPrimaryActionPromptsFreshMicrophonePermission() {
        XCTAssertEqual(
            OnboardingPermissionPrimaryActionPolicy.primaryButtonTitle(
                microphoneStatus: .requestable,
                accessibilityStatus: .denied,
                systemAudioReadiness: .setupNeeded,
                restartRecommended: false,
                language: .english
            ),
            "Grant Microphone"
        )
    }

    func testOnboardingPrimaryActionOpensMicrophoneSettingsAfterDeniedDecision() {
        XCTAssertEqual(
            OnboardingPermissionPrimaryActionPolicy.primaryButtonTitle(
                microphoneStatus: .settingsRequired,
                accessibilityStatus: .denied,
                systemAudioReadiness: .setupNeeded,
                restartRecommended: false,
                language: .english
            ),
            "Open Microphone Settings"
        )
    }

    func testOnboardingPrimaryActionUsesRussianCopy() {
        XCTAssertEqual(
            OnboardingPermissionPrimaryActionPolicy.primaryButtonTitle(
                microphoneStatus: .requestable,
                accessibilityStatus: .denied,
                systemAudioReadiness: .setupNeeded,
                restartRecommended: false,
                language: .russian
            ),
            "Разрешить микрофон"
        )
        XCTAssertEqual(
            OnboardingPermissionPrimaryActionPolicy.microphoneRowActionLabel(
                microphoneStatus: .settingsRequired,
                language: .russian
            ),
            "Открыть настройки"
        )
    }

    func testOnboardingPrimaryActionKeepsSystemAudioSetupNonBlocking() {
        XCTAssertEqual(
            OnboardingPermissionPrimaryActionPolicy.primaryButtonTitle(
                microphoneStatus: .granted,
                accessibilityStatus: .granted,
                systemAudioReadiness: .setupNeeded,
                restartRecommended: false,
                language: .english
            ),
            "Continue",
            "The Core Audio prompt can still be completed from onboarding, Settings, or the first dual-source dictation."
        )
    }

    func testOnboardingPrimaryActionContinuesWhenSystemAudioIsReady() {
        XCTAssertEqual(
            OnboardingPermissionPrimaryActionPolicy.primaryButtonTitle(
                microphoneStatus: .granted,
                accessibilityStatus: .granted,
                systemAudioReadiness: .ready,
                restartRecommended: false,
                language: .english
            ),
            "Continue"
        )
    }

    func testOnboardingPrimaryActionAllowsExplicitLegacyMicrophoneOnlyMode() {
        XCTAssertEqual(
            OnboardingPermissionPrimaryActionPolicy.primaryButtonTitle(
                microphoneStatus: .granted,
                accessibilityStatus: .granted,
                systemAudioReadiness: .unsupported,
                restartRecommended: false,
                language: .english
            ),
            "Continue",
            "macOS versions without Core Audio process taps must remain usable with explicit compatibility copy."
        )
    }

    func testRecordingImportCopyUsesSelectedLanguage() {
        XCTAssertEqual(
            RecordingCopy.importPanelTitle(language: .english),
            "Import Audio or Video"
        )
        XCTAssertEqual(
            RecordingCopy.importPanelTitle(language: .russian),
            "Импорт аудио или видео"
        )
        XCTAssertFalse(
            RecordingCopy.importProcessingFailedFallback(language: .russian)
                .contains("transcribe")
        )
    }

    func testSystemAudioCaptureErrorCopyUsesSelectedLanguage() {
        XCTAssertEqual(
            RecordingCopy.systemAudioCaptureUnavailableMessage(language: .english),
            "System audio capture couldn't start. Check Audio Capture permission in System Settings and try again."
        )
        XCTAssertFalse(
            RecordingCopy.systemAudioCaptureUnavailableMessage(language: .russian)
                .contains("System audio capture")
        )
    }

    @available(macOS 14.2, *)
    func testDualCaptureAcceptsTheSharedEngineLiveMicrophoneStream() {
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        continuation.finish()

        let capture = DualAudioCapture(liveMicrophoneBuffers: stream)

        XCTAssertFalse(capture.isRecording)
        XCTAssertTrue(capture.mixToMono)
        XCTAssertFalse(capture.isSystemAudioStreamHealthy)
    }

    func testDictationManagerWiresSystemAudioWithoutReturningToPerPressMicrophoneCapture() throws {
        let source = try repositorySource(
            "macos/WaiComputer/WaiComputer/Features/Dictation/DictationManager.swift"
        )

        XCTAssertTrue(source.contains("DualAudioCapture(liveMicrophoneBuffers: lease.buffers)"))
        XCTAssertTrue(source.contains("try await dualCapture.startRecording()"))
        XCTAssertTrue(source.contains("activeDictationAudioCapture"))
        XCTAssertFalse(source.contains("MicrophoneCapture()"))
    }

    func testSettingsPrivacyCopyNamesBothActiveDictationAudioSources() throws {
        let source = try repositorySource(
            "macos/WaiComputer/WaiComputer/Features/Settings/MacSettingsView.swift"
        )

        XCTAssertTrue(source.contains("microphone and system audio only while you are actively dictating"))
        XCTAssertTrue(source.contains("микрофона и системный звук только во время активной диктовки"))
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

    func testSystemAudioReadinessMapsToPermissionRowStatus() {
        XCTAssertEqual(SystemAudioReadinessPolicy.permissionStatus(for: .ready), .granted)
        XCTAssertEqual(SystemAudioReadinessPolicy.permissionStatus(for: .restartRequired), .staleNeedsRestart)
        XCTAssertEqual(SystemAudioReadinessPolicy.permissionStatus(for: .setupNeeded), .denied)
        XCTAssertEqual(SystemAudioReadinessPolicy.permissionStatus(for: .unsupported), .denied)
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

    private func repositorySource(_ relativePath: String) throws -> String {
        var repositoryRoot = URL(fileURLWithPath: #filePath)
        for _ in 0..<4 {
            repositoryRoot.deleteLastPathComponent()
        }
        return try String(
            contentsOf: repositoryRoot.appendingPathComponent(relativePath),
            encoding: .utf8
        )
    }
}
