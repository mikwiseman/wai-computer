import XCTest
import Sentry
@testable import WaiComputerKit

/// Tests for the DictationInstrumentation singleton. Because state is process-wide,
/// each test measures *deltas* in counters rather than absolute values.
final class DictationInstrumentationTests: XCTestCase {

    private var inst: DictationInstrumentation { DictationInstrumentation.shared }

    // MARK: - Event categories and levels

    func testEventCategories() {
        XCTAssertEqual(DictationInstrumentation.Event.armingStarted.category, "dictation.session")
        XCTAssertEqual(DictationInstrumentation.Event.audioFirstChunkSent.category, "dictation.session")
        XCTAssertEqual(DictationInstrumentation.Event.finalizingStarted.category, "dictation.session")
        XCTAssertEqual(DictationInstrumentation.Event.transcriptFinalized.category, "dictation.session")
        XCTAssertEqual(DictationInstrumentation.Event.insertionStarted.category, "dictation.session")
        XCTAssertEqual(DictationInstrumentation.Event.insertionCompleted.category, "dictation.session")
        XCTAssertEqual(DictationInstrumentation.Event.sessionCompleted.category, "dictation.session")
        XCTAssertEqual(DictationInstrumentation.Event.sessionCancelled.category, "dictation.session")

        XCTAssertEqual(DictationInstrumentation.Event.audioLeaseAcquired.category, "dictation.audio")
        XCTAssertEqual(DictationInstrumentation.Event.audioLeaseReleased.category, "dictation.audio")
        XCTAssertEqual(DictationInstrumentation.Event.audioContinuationDropped.category, "dictation.audio")

        XCTAssertEqual(DictationInstrumentation.Event.tokenMinted.category, "dictation.token")
        XCTAssertEqual(DictationInstrumentation.Event.tokenPrefetchHit.category, "dictation.token")
        XCTAssertEqual(DictationInstrumentation.Event.tokenPrefetchMiss.category, "dictation.token")

        XCTAssertEqual(DictationInstrumentation.Event.providerConnecting.category, "dictation.provider")
        XCTAssertEqual(DictationInstrumentation.Event.providerOpened.category, "dictation.provider")
        XCTAssertEqual(DictationInstrumentation.Event.providerWarning.category, "dictation.provider")
        XCTAssertEqual(DictationInstrumentation.Event.providerClosed.category, "dictation.provider")
        XCTAssertEqual(DictationInstrumentation.Event.firstTokenReceived.category, "dictation.provider")
        XCTAssertEqual(DictationInstrumentation.Event.interimTranscript.category, "dictation.provider")
        XCTAssertEqual(DictationInstrumentation.Event.committedTranscript.category, "dictation.provider")

        XCTAssertEqual(DictationInstrumentation.Event.cleanupRequested.category, "dictation.cleanup")
        XCTAssertEqual(DictationInstrumentation.Event.cleanupCompleted.category, "dictation.cleanup")
        XCTAssertEqual(DictationInstrumentation.Event.cleanupSkipped.category, "dictation.cleanup")
    }

    func testEventLevels() {
        XCTAssertEqual(DictationInstrumentation.Event.providerWarning.level, .warning)
        XCTAssertEqual(DictationInstrumentation.Event.audioContinuationDropped.level, .warning)
        XCTAssertEqual(DictationInstrumentation.Event.tokenPrefetchMiss.level, .warning)
        XCTAssertEqual(DictationInstrumentation.Event.sessionCancelled.level, .warning)

        XCTAssertEqual(DictationInstrumentation.Event.armingStarted.level, .info)
        XCTAssertEqual(DictationInstrumentation.Event.tokenMinted.level, .info)
        XCTAssertEqual(DictationInstrumentation.Event.providerOpened.level, .info)
        XCTAssertEqual(DictationInstrumentation.Event.sessionCompleted.level, .info)
    }

    func testEventRawValues() {
        // Spot-check a few rawValue strings: these are part of the wire contract
        // (Sentry breadcrumb messages, signpost names) and changing them silently
        // would break dashboards.
        XCTAssertEqual(DictationInstrumentation.Event.armingStarted.rawValue, "arming.start")
        XCTAssertEqual(DictationInstrumentation.Event.firstTokenReceived.rawValue, "transcript.first_token")
        XCTAssertEqual(DictationInstrumentation.Event.sessionCompleted.rawValue, "session.completed")
        XCTAssertEqual(DictationInstrumentation.Event.sessionCancelled.rawValue, "session.cancelled")
        XCTAssertEqual(DictationInstrumentation.Event.tokenPrefetchHit.rawValue, "token.prefetch.hit")
    }

    // MARK: - Session counter behaviour

    func testStartSessionIncrementsCounter() {
        let before = inst.snapshot().sessionsStarted
        let session = inst.startSession()
        let after = inst.snapshot().sessionsStarted
        XCTAssertEqual(after, before + 1)
        // Clean up by completing the session
        session.cancel(reason: "test_cleanup")
    }

    func testSuccessOutcomeRecorded() {
        let before = inst.snapshot()
        let session = inst.startSession()
        session.succeed()
        let after = inst.snapshot()
        XCTAssertEqual(after.sessionsSucceeded, before.sessionsSucceeded + 1)
        XCTAssertEqual(after.consecutiveFailures, 0, "success resets consecutive failures")
    }

    func testFailureOutcomeIncrementsConsecutiveFailures() {
        // Reset the streak first
        let resetSession = inst.startSession()
        resetSession.succeed()

        let baseline = inst.snapshot()
        XCTAssertEqual(baseline.consecutiveFailures, 0)

        struct TestErr: Error {}

        let s1 = inst.startSession()
        s1.failure(TestErr())
        XCTAssertEqual(inst.snapshot().consecutiveFailures, 1)

        let s2 = inst.startSession()
        s2.failure(TestErr())
        XCTAssertEqual(inst.snapshot().consecutiveFailures, 2)

        // Success resets
        let s3 = inst.startSession()
        s3.succeed()
        XCTAssertEqual(inst.snapshot().consecutiveFailures, 0)
    }

    func testCancelResetsConsecutiveFailures() {
        // Build up a failure streak first
        let reset = inst.startSession(); reset.succeed()
        struct TestErr: Error {}
        let f1 = inst.startSession(); f1.failure(TestErr())
        let f2 = inst.startSession(); f2.failure(TestErr())
        XCTAssertGreaterThanOrEqual(inst.snapshot().consecutiveFailures, 2)

        let cancelled = inst.startSession()
        cancelled.cancel(reason: "user_release")
        XCTAssertEqual(inst.snapshot().consecutiveFailures, 0)
    }

    func testCancelIncrementsCancelledCounter() {
        let before = inst.snapshot().sessionsCancelled
        let session = inst.startSession()
        session.cancel(reason: "test")
        let after = inst.snapshot().sessionsCancelled
        XCTAssertEqual(after, before + 1)
    }

    func testConsecutiveFailureCountAccessor() {
        // Reset then build a known streak
        let reset = inst.startSession(); reset.succeed()
        XCTAssertEqual(inst.consecutiveFailureCount(), 0)

        struct E: Error {}
        let s = inst.startSession()
        s.failure(E())
        XCTAssertEqual(inst.consecutiveFailureCount(), 1)
    }

    // MARK: - First-token latency

    func testFirstTokenLatencyOnlyRecordedOncePerSession() throws {
        let session = inst.startSession()

        // First firstTokenReceived sets the latency
        session.event(.firstTokenReceived)
        Thread.sleep(forTimeInterval: 0.02) // 20ms
        // Second firstTokenReceived should be ignored (latency already locked in)
        session.event(.firstTokenReceived)

        session.succeed()

        // After success, the latency should have a sample close to ~0ms
        // (not ~20ms — proving the second event was ignored).
        let samples = inst.snapshot().firstTokenLatencyMs
        XCTAssertGreaterThanOrEqual(samples.count, 1)
        let last = try XCTUnwrap(samples.last)
        XCTAssertLessThan(last, 20, "first firstTokenReceived locked in latency before the 20ms sleep")
    }

    func testFailureDoesNotRecordLatency() {
        let beforeCount = inst.snapshot().firstTokenLatencyMs.count
        let session = inst.startSession()
        struct E: Error {}
        session.failure(E())
        let afterCount = inst.snapshot().firstTokenLatencyMs.count
        XCTAssertEqual(afterCount, beforeCount, "failed sessions don't append to first-token latency ring")
    }

    // MARK: - Idempotent finish

    func testFinishIsIdempotent() {
        let before = inst.snapshot().sessionsSucceeded
        let session = inst.startSession()
        session.succeed()
        // Calling succeed again must not double-count
        session.succeed()
        // Calling cancel after succeed must not double-count
        session.cancel(reason: "after_success")
        let after = inst.snapshot().sessionsSucceeded
        XCTAssertEqual(after, before + 1, "only the first finish counts")
    }

    // MARK: - Ring buffer cap

    func testLatencyRingBufferCaps() {
        // The ring is bounded at 50 samples. Push 60 successful sessions and
        // verify the ring is exactly capped at 50.
        for _ in 0..<60 {
            let s = inst.startSession()
            s.event(.firstTokenReceived)
            s.succeed()
        }
        let samples = inst.snapshot().firstTokenLatencyMs
        XCTAssertLessThanOrEqual(samples.count, 50, "ring buffer caps at 50 samples")
        XCTAssertEqual(samples.count, 50, "ring should fill to exactly 50 after >50 pushes")
    }

    // MARK: - Session identity

    func testEachSessionHasUniqueId() {
        let s1 = inst.startSession()
        let s2 = inst.startSession()
        XCTAssertNotEqual(s1.id, s2.id)
        s1.cancel(reason: "cleanup")
        s2.cancel(reason: "cleanup")
    }

    func testSessionStartedAtIsRecent() {
        let beforeWall = ContinuousClock().now
        let session = inst.startSession()
        let afterWall = ContinuousClock().now
        XCTAssertGreaterThanOrEqual(session.startedAt, beforeWall)
        XCTAssertLessThanOrEqual(session.startedAt, afterWall)
        session.cancel(reason: "cleanup")
    }

    // MARK: - DictationInstrumentationError

    func testErrorDescriptions() {
        let mic = DictationInstrumentationError.microphoneDenied
        XCTAssertEqual(mic.errorDescription, "Microphone permission denied")

        let auth = DictationInstrumentationError.notAuthenticated
        XCTAssertEqual(auth.errorDescription, "Not authenticated")

        let unknown = DictationInstrumentationError.unknown("boom")
        XCTAssertEqual(unknown.errorDescription, "Dictation failed: boom")
    }
}
