import WaiComputerKit
import XCTest

final class DeferredDictationStopPolicyTests: XCTestCase {
    private var tempDirectory: URL?

    override func tearDownWithError() throws {
        if let tempDirectory {
            try? FileManager.default.removeItem(at: tempDirectory)
        }
        tempDirectory = nil
        try super.tearDownWithError()
    }

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
        XCTAssertEqual(
            DictationFinalizationPolicy.captureTailDelay(
                tapBufferFrames: 2_048,
                sampleRate: 48_000
            ),
            .milliseconds(166)
        )
    }

    func testFinalizationTailIsBoundedForLargeTapBuffers() {
        XCTAssertEqual(
            DictationFinalizationPolicy.captureTailDelay(
                tapBufferFrames: 16_384,
                sampleRate: 16_000
            ),
            .milliseconds(450)
        )
    }

    func testFinalizationTailKeepsMinimumSafetyWindow() {
        XCTAssertEqual(
            DictationFinalizationPolicy.captureTailDelay(
                tapBufferFrames: 256,
                sampleRate: 48_000
            ),
            .milliseconds(150)
        )
    }

    func testCleanupDisabledUsesRawTranscript() {
        let resolution = DictationCleanupPolicy.resolve(
            rawText: "raw transcript",
            cleanupEnabled: false,
            cleanedText: nil,
            cleanupError: nil
        )

        XCTAssertEqual(resolution.text, "raw transcript")
        XCTAssertNil(resolution.cleanupFallbackNotice)
    }

    func testCleanupEnabledUsesCleanedTranscript() {
        let resolution = DictationCleanupPolicy.resolve(
            rawText: "raw transcript",
            cleanupEnabled: true,
            cleanedText: "Cleaned transcript.",
            cleanupError: nil
        )

        XCTAssertEqual(resolution.text, "Cleaned transcript.")
        XCTAssertNil(resolution.cleanupFallbackNotice)
    }

    func testCleanupEnabledFailureInsertsRawTranscriptWithNotice() {
        // Words are never dropped because the post-processor was down: the raw
        // transcript lands and the degradation is reported via the notice.
        let resolution = DictationCleanupPolicy.resolve(
            rawText: "raw transcript",
            cleanupEnabled: true,
            cleanedText: nil,
            cleanupError: URLError(.cannotConnectToHost)
        )

        XCTAssertEqual(resolution.text, "raw transcript")
        XCTAssertEqual(
            resolution.cleanupFallbackNotice,
            DictationCleanupPolicy.fallbackNotice
        )
    }

    func testCleanupEnabledBlankResultInsertsRawTranscriptWithNotice() {
        let resolution = DictationCleanupPolicy.resolve(
            rawText: "raw transcript",
            cleanupEnabled: true,
            cleanedText: "   ",
            cleanupError: nil
        )

        XCTAssertEqual(resolution.text, "raw transcript")
        XCTAssertNotNil(resolution.cleanupFallbackNotice)
    }

    func testCleanupTimeoutInsertsRawTranscriptWithTimeoutNotice() {
        let resolution = DictationCleanupPolicy.resolve(
            rawText: "raw transcript",
            cleanupEnabled: true,
            cleanedText: nil,
            cleanupError: DictationCleanupTimeoutError(timeoutSeconds: 4)
        )

        XCTAssertEqual(resolution.text, "raw transcript")
        XCTAssertEqual(
            resolution.cleanupFallbackNotice,
            DictationCleanupPolicy.timeoutNotice
        )
    }

    func testCleanupDeadlineIsAGenerousWatchdogForLightCleanup() {
        XCTAssertEqual(
            DictationCleanupDeadlinePolicy.timeoutSeconds(
                cleanupLevel: "light",
                rawTextCharacterCount: 240
            ),
            10
        )
    }

    func testCleanupDeadlineGivesMoreTimeToExplicitHighCleanup() {
        XCTAssertEqual(
            DictationCleanupDeadlinePolicy.timeoutSeconds(
                cleanupLevel: "high",
                rawTextCharacterCount: 240
            ),
            16
        )
    }

    func testCleanupDeadlineScalesWithLengthButCapsExtraWait() {
        XCTAssertEqual(
            DictationCleanupDeadlinePolicy.timeoutSeconds(
                cleanupLevel: "medium",
                rawTextCharacterCount: 30_000
            ),
            24
        )
    }

    func testCleanupDeadlineTreatsUnknownLevelAsLight() {
        XCTAssertEqual(
            DictationCleanupDeadlinePolicy.timeoutSeconds(
                cleanupLevel: "unexpected",
                rawTextCharacterCount: -1
            ),
            10
        )
    }

    @MainActor
    func testDictionaryVocabularyIncludesReplacementSpellingsForCleanup() throws {
        let store = try makeTemporaryDictionaryStore()

        XCTAssertTrue(store.add(word: "Bolnichny", replacement: "больничный"))
        XCTAssertTrue(store.add(word: "WaiComputer"))

        XCTAssertEqual(
            Set(store.vocabularyList),
            Set(["Bolnichny", "больничный", "WaiComputer"])
        )
    }

    @MainActor
    func testDictionaryRealtimeHintsIncludeKeytermsAndReplacementPairs() throws {
        let store = try makeTemporaryDictionaryStore()

        XCTAssertTrue(store.add(word: "Bolnichny", replacement: "больничный"))
        XCTAssertTrue(store.add(word: "WaiComputer"))

        let hints = store.realtimeHints

        XCTAssertEqual(
            Set(hints.keyterms),
            Set(["Bolnichny", "больничный", "WaiComputer"])
        )
        XCTAssertEqual(
            hints.replacements,
            [
                RealtimeTranscriptionReplacement(find: "Bolnichny", replace: "больничный"),
            ]
        )
    }

    @MainActor
    func testDictionaryStoreNotifiesRealtimeHintChangesOncePerLogicalEdit() throws {
        let store = try makeTemporaryDictionaryStore()
        var reasons: [String] = []
        store.onRealtimeHintsChanged = { reason in
            reasons.append(reason)
        }

        XCTAssertTrue(store.add(word: "WaiComputer"))
        store.learnReplacement(word: "why computer", replacement: "WaiComputer")
        guard let firstWord = store.words.first(where: { $0.word == "WaiComputer" }) else {
            return XCTFail("Expected dictionary entry")
        }
        XCTAssertTrue(
            store.update(
                firstWord,
                newWord: "WaiComputer",
                newReplacement: "Wai Computer"
            )
        )
        guard let learnedWord = store.words.first(where: { $0.word == "why computer" }) else {
            return XCTFail("Expected learned replacement")
        }
        store.delete(learnedWord)

        XCTAssertEqual(
            reasons,
            [
                "dictionary_add",
                "dictionary_learn_replacement",
                "dictionary_update",
                "dictionary_delete",
            ]
        )
    }

    @MainActor
    func testDictionaryPhraseReplacementToleratesPunctuationBetweenWords() throws {
        let store = try makeTemporaryDictionaryStore()
        store.learnReplacement(word: "why computer", replacement: "WaiComputer")

        XCTAssertEqual(
            store.applyReplacements(to: "open why, computer now"),
            "open WaiComputer now"
        )
        XCTAssertEqual(
            store.applyReplacements(to: "open whycomputer now"),
            "open whycomputer now"
        )
    }

    func testTokenRemintTriggersOnHandshakeAuthCloseAndAuthError() {
        // A stale prefetched token is rejected as a 1008/1011 close DURING the
        // websocket handshake — the dominant real-world shape.
        XCTAssertTrue(
            DictationTokenRetryPolicy.shouldRemint(
                after: WebSocketHandshakeCoordinator.HandshakeError.closedBeforeOpen(
                    closeCode: .policyViolation,
                    reason: "bad token"
                )
            )
        )
        XCTAssertTrue(
            DictationTokenRetryPolicy.shouldRemint(
                after: WebSocketHandshakeCoordinator.HandshakeError.closedBeforeOpen(
                    closeCode: .internalServerError,
                    reason: nil
                )
            )
        )
        XCTAssertTrue(
            DictationTokenRetryPolicy.shouldRemint(
                after: ProviderError.authError(server: "invalid_api_key")
            )
        )
    }

    func testTokenRemintSkipsNonAuthFailures() {
        XCTAssertFalse(
            DictationTokenRetryPolicy.shouldRemint(
                after: WebSocketHandshakeCoordinator.HandshakeError.timedOut
            )
        )
        XCTAssertFalse(
            DictationTokenRetryPolicy.shouldRemint(
                after: WebSocketHandshakeCoordinator.HandshakeError.closedBeforeOpen(
                    closeCode: .normalClosure,
                    reason: nil
                )
            )
        )
        XCTAssertFalse(
            DictationTokenRetryPolicy.shouldRemint(after: URLError(.notConnectedToInternet))
        )
        XCTAssertFalse(
            DictationTokenRetryPolicy.shouldRemint(after: ProviderError.quotaExceeded)
        )
    }

    func testCleanupSpeculationReusesExactFinalTranscriptMatch() {
        XCTAssertEqual(
            DictationCleanupSpeculationPolicy.decision(
                preliminaryRawText: "Clean this transcript.",
                finalRawText: "Clean this transcript."
            ),
            .reuseSpeculative
        )
    }

    func testCleanupSpeculationReusesNormalizedFinalTranscriptMatch() {
        XCTAssertEqual(
            DictationCleanupSpeculationPolicy.decision(
                preliminaryRawText: "Clean this transcript",
                finalRawText: "clean this transcript."
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

    func testCleanupSpeculationStartsForStableCommittedTranscript() {
        XCTAssertTrue(
            DictationCleanupSpeculationStartPolicy.shouldStart(
                committedText: "Clean this transcript.",
                currentInterim: ""
            )
        )
    }

    func testCleanupSpeculationDoesNotStartWithOnlyInterimTranscript() {
        XCTAssertFalse(
            DictationCleanupSpeculationStartPolicy.shouldStart(
                committedText: "",
                currentInterim: "Clean this transcript"
            )
        )
    }

    func testCleanupSpeculationDoesNotStartWithPendingInterimTail() {
        XCTAssertFalse(
            DictationCleanupSpeculationStartPolicy.shouldStart(
                committedText: "Clean this transcript.",
                currentInterim: "Clean this"
            )
        )
    }

    func testCleanupSpeculationBackfillsAlreadyAccumulatedPreviewOnReuse() {
        XCTAssertEqual(
            DictationCleanupSpeculationPreviewPolicy.visiblePreviewOnReuse(
                storedPreview: "Cleaned text already streamed"
            ),
            "Cleaned text already streamed"
        )
    }

    func testCleanupSpeculationUsesBlankPreviewWhenNoTokensHaveArrived() {
        XCTAssertEqual(
            DictationCleanupSpeculationPreviewPolicy.visiblePreviewOnReuse(storedPreview: nil),
            ""
        )
    }

    func testFinalizationContinuesOnlyWhenNotCancelled() {
        XCTAssertTrue(
            DictationFinalizationContinuationPolicy.shouldContinue(
                state: .finalizing,
                cancellationRequested: false,
                taskCancelled: false
            )
        )
        XCTAssertFalse(
            DictationFinalizationContinuationPolicy.shouldContinue(
                state: .finalizing,
                cancellationRequested: true,
                taskCancelled: false
            )
        )
        XCTAssertFalse(
            DictationFinalizationContinuationPolicy.shouldContinue(
                state: .finalizing,
                cancellationRequested: false,
                taskCancelled: true
            )
        )
        XCTAssertFalse(
            DictationFinalizationContinuationPolicy.shouldContinue(
                state: .idle,
                cancellationRequested: false,
                taskCancelled: false
            )
        )
    }

    // MARK: - TextInsertionActivationPolicy

    func testInsertionSkipsActivationWaitWhenTargetAlreadyActive() {
        XCTAssertFalse(
            TextInsertionActivationPolicy.shouldWaitAfterActivation(
                targetWasActive: true,
                activationReportedSuccessful: true
            )
        )
    }

    func testInsertionWaitsAfterActivatingInactiveTarget() {
        XCTAssertTrue(
            TextInsertionActivationPolicy.shouldWaitAfterActivation(
                targetWasActive: false,
                activationReportedSuccessful: true
            )
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

    @MainActor
    private func makeTemporaryDictionaryStore() throws -> DictationDictionaryStore {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("DictationDictionaryStoreTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        tempDirectory = directory
        return DictationDictionaryStore(
            fileURL: directory.appendingPathComponent("dictation_dictionary.json"),
            tombstonesURL: directory.appendingPathComponent("dictation_dictionary_tombstones.json")
        )
    }
}
