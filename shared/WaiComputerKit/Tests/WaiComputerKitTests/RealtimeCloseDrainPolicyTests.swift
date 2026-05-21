import XCTest
@testable import WaiComputerKit

final class RealtimeCloseDrainPolicyTests: XCTestCase {
    func testStopsAfterShortNoTranscriptWindowBeforeDeadline() {
        let clock = ContinuousClock()
        let startedAt = clock.now

        XCTAssertTrue(RealtimeCloseDrainPolicy.shouldKeepWaiting(
            now: startedAt + .milliseconds(899),
            deadline: startedAt + .seconds(3),
            startedAt: startedAt,
            lastTranscriptEventAt: nil,
            finalizationMarkerReceived: false
        ))
        XCTAssertFalse(RealtimeCloseDrainPolicy.shouldKeepWaiting(
            now: startedAt + .milliseconds(900),
            deadline: startedAt + .seconds(3),
            startedAt: startedAt,
            lastTranscriptEventAt: nil,
            finalizationMarkerReceived: false
        ))
    }

    func testStopsAfterFinalizationMarkerAndMinimumWait() {
        let clock = ContinuousClock()
        let startedAt = clock.now

        XCTAssertTrue(RealtimeCloseDrainPolicy.shouldKeepWaiting(
            now: startedAt + .milliseconds(249),
            deadline: startedAt + .seconds(3),
            startedAt: startedAt,
            lastTranscriptEventAt: nil,
            finalizationMarkerReceived: true
        ))
        XCTAssertFalse(RealtimeCloseDrainPolicy.shouldKeepWaiting(
            now: startedAt + .milliseconds(250),
            deadline: startedAt + .seconds(3),
            startedAt: startedAt,
            lastTranscriptEventAt: nil,
            finalizationMarkerReceived: true
        ))
    }

    func testWaitsForQuietWindowAfterTranscriptEvent() {
        let clock = ContinuousClock()
        let startedAt = clock.now
        let transcriptAt = startedAt + .milliseconds(600)

        XCTAssertTrue(RealtimeCloseDrainPolicy.shouldKeepWaiting(
            now: transcriptAt + .milliseconds(499),
            deadline: startedAt + .seconds(3),
            startedAt: startedAt,
            lastTranscriptEventAt: transcriptAt,
            finalizationMarkerReceived: false
        ))
        XCTAssertFalse(RealtimeCloseDrainPolicy.shouldKeepWaiting(
            now: transcriptAt + .milliseconds(500),
            deadline: startedAt + .seconds(3),
            startedAt: startedAt,
            lastTranscriptEventAt: transcriptAt,
            finalizationMarkerReceived: false
        ))
    }
}
