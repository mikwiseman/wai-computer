import XCTest

final class DeferredDictationStopPolicyTests: XCTestCase {
    func testPushToTalkReleaseDuringConnectFinishesAfterReady() {
        XCTAssertEqual(
            DeferredDictationStopPolicy.action(deferredStop: true, isHandsFree: false),
            .finishAfterReady
        )
    }

    func testHandsFreeIgnoresDeferredPushToTalkStop() {
        XCTAssertEqual(
            DeferredDictationStopPolicy.action(deferredStop: true, isHandsFree: true),
            .continueListening
        )
    }

    func testNoDeferredStopContinuesListening() {
        XCTAssertEqual(
            DeferredDictationStopPolicy.action(deferredStop: false, isHandsFree: false),
            .continueListening
        )
    }

    func testFinalizationKeepsShortAudioTailBeforeStoppingCapture() {
        XCTAssertEqual(DictationFinalizationPolicy.captureTailDelay, .milliseconds(450))
    }

    func testCleanupDisabledUsesRawTranscript() throws {
        let text = try DictationCleanupPolicy.textToInsert(
            rawText: "raw transcript",
            cleanupEnabled: false,
            cleanedText: nil,
            cleanupError: nil
        )

        XCTAssertEqual(text, "raw transcript")
    }

    func testCleanupEnabledUsesCleanedTranscript() throws {
        let text = try DictationCleanupPolicy.textToInsert(
            rawText: "raw transcript",
            cleanupEnabled: true,
            cleanedText: "Cleaned transcript.",
            cleanupError: nil
        )

        XCTAssertEqual(text, "Cleaned transcript.")
    }

    func testCleanupEnabledFailureAbortsInsteadOfUsingRawTranscript() {
        XCTAssertThrowsError(
            try DictationCleanupPolicy.textToInsert(
                rawText: "raw transcript",
                cleanupEnabled: true,
                cleanedText: nil,
                cleanupError: URLError(.cannotConnectToHost)
            )
        ) { error in
            XCTAssertEqual((error as? URLError)?.code, .cannotConnectToHost)
        }
    }

    func testCleanupEnabledBlankResultAbortsInsteadOfInsertingEmptyText() {
        XCTAssertThrowsError(
            try DictationCleanupPolicy.textToInsert(
                rawText: "raw transcript",
                cleanupEnabled: true,
                cleanedText: "   ",
                cleanupError: nil
            )
        )
    }

    func testCleanupSpeculationReusesOnlyExactFinalTranscriptMatch() {
        XCTAssertEqual(
            DictationCleanupSpeculationPolicy.decision(
                preliminaryRawText: "Clean this transcript.",
                finalRawText: "Clean this transcript."
            ),
            .reuseSpeculative
        )
    }

    func testCleanupSpeculationRestartsWhenFinalTranscriptDiffers() {
        XCTAssertEqual(
            DictationCleanupSpeculationPolicy.decision(
                preliminaryRawText: "Clean this transcript.",
                finalRawText: "Clean this transcript better."
            ),
            .restartWithFinal
        )
    }

    func testCleanupSpeculationRestartsWithoutPreliminaryTranscript() {
        XCTAssertEqual(
            DictationCleanupSpeculationPolicy.decision(
                preliminaryRawText: " ",
                finalRawText: "Clean this transcript."
            ),
            .restartWithFinal
        )
    }

    // MARK: - PushToTalkStopPolicy

    func testListeningHotkeyReleaseFinishesNow() {
        XCTAssertEqual(
            PushToTalkStopPolicy.resolve(state: .listening, isHandsFree: false),
            .finishNow
        )
    }

    func testConnectingHotkeyReleaseDefersUntilReady() {
        // The user released the hotkey while the realtime WS handshake is
        // still in flight. The start path picks the deferred-stop signal up
        // the moment state transitions to .listening — without this we'd
        // tear down a half-open session via cancelDictation and lose any
        // audio captured in DictationStartupAudioBuffer.
        XCTAssertEqual(
            PushToTalkStopPolicy.resolve(state: .connecting, isHandsFree: false),
            .deferUntilReady
        )
    }

    func testIdleHotkeyReleaseDefersUntilReady() {
        // Race: onPushToTalkStart fired, Task was created, but startDictation
        // hasn't yet executed setState(.connecting). Without deferring, the
        // session would go live with no holder and behave like a stuck
        // hands-free session until the next press.
        XCTAssertEqual(
            PushToTalkStopPolicy.resolve(state: .idle, isHandsFree: false),
            .deferUntilReady
        )
    }

    func testFinalizingHotkeyReleaseDoesNothing() {
        XCTAssertEqual(
            PushToTalkStopPolicy.resolve(state: .finalizing, isHandsFree: false),
            .doNothing
        )
    }

    func testHandsFreeIgnoresHotkeyRelease() {
        for state in [PushToTalkStopState.idle, .connecting, .listening, .finalizing] {
            XCTAssertEqual(
                PushToTalkStopPolicy.resolve(state: state, isHandsFree: true),
                .doNothing,
                "state \(state) should be doNothing in hands-free mode"
            )
        }
    }

    // MARK: - HotkeyReleasePolicy

    func testHotkeyReleaseFiresStopAfterTimerWithCleanHold() {
        // Normal happy path: held past threshold, timer fired,
        // no modifier conflict — fire onPushToTalkStop.
        XCTAssertEqual(
            HotkeyReleasePolicy.action(
                isInPushToTalk: true,
                otherKeyPressed: false,
                holdDuration: 0.20,
                holdThreshold: 0.08
            ),
            .pushToTalkStop
        )
    }

    func testHotkeyReleaseAtBoundaryWithTimerFiredStillFiresStop() {
        // The headline bug: timer fired (isInPushToTalk=true) but Date()
        // reads holdDuration just under holdThreshold due to scheduler
        // jitter. Previously this branch fired .cancelled which tore down
        // a dictation session that ALREADY started ~80 ms earlier — that
        // was the user-visible "starts then immediately stops" symptom on
        // borderline-fast presses.
        XCTAssertEqual(
            HotkeyReleasePolicy.action(
                isInPushToTalk: true,
                otherKeyPressed: false,
                holdDuration: 0.078,  // < threshold but timer already fired
                holdThreshold: 0.08
            ),
            .pushToTalkStop
        )
    }

    func testHotkeyReleaseWithModifierConflictCancelsEvenAfterStart() {
        // User pressed another key while holding — real shortcut, not
        // dictation. Cancel even though the timer fired.
        XCTAssertEqual(
            HotkeyReleasePolicy.action(
                isInPushToTalk: true,
                otherKeyPressed: true,
                holdDuration: 0.50,
                holdThreshold: 0.08
            ),
            .cancelled
        )
    }

    func testShortReleaseBeforeTimerFiresIsSingleTap() {
        XCTAssertEqual(
            HotkeyReleasePolicy.action(
                isInPushToTalk: false,
                otherKeyPressed: false,
                holdDuration: 0.05,
                holdThreshold: 0.08
            ),
            .singleTap
        )
    }

    func testShortReleaseWithModifierConflictIsCancelled() {
        XCTAssertEqual(
            HotkeyReleasePolicy.action(
                isInPushToTalk: false,
                otherKeyPressed: true,
                holdDuration: 0.05,
                holdThreshold: 0.08
            ),
            .cancelled
        )
    }
}
