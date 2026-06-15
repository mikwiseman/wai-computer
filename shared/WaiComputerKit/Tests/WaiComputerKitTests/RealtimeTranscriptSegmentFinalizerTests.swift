import XCTest
@testable import WaiComputerKit

final class RealtimeTranscriptSegmentFinalizerTests: XCTestCase {
    func testPrefersFullerLiveTranscriptWhenProviderFinalDroppedStartupWords() {
        let providerSegments = [
            LiveTranscriptSegment(
                text: "check fast startup",
                speaker: "speaker_0",
                isFinal: true,
                startMs: 800,
                endMs: 2_400,
                confidence: 0.92
            )
        ]

        let segments = RealtimeTranscriptSegmentFinalizer.finalizedSegments(
            providerSegments: providerSegments,
            liveTranscript: "today we check fast startup",
            liveSpeaker: nil,
            durationSeconds: 3,
            didFinalize: true
        )

        XCTAssertEqual(segments.map(\.text), ["today we check fast startup"])
        XCTAssertEqual(segments.first?.speaker, "speaker_0")
        XCTAssertEqual(segments.first?.startMs, 0)
        XCTAssertEqual(segments.first?.endMs, 3_000)
    }

    func testKeepsProviderSegmentsWhenLiveTranscriptOnlyAddsUnfinalizedTail() {
        let providerSegments = [
            LiveTranscriptSegment(
                text: "send the report",
                speaker: nil,
                isFinal: true,
                startMs: 0,
                endMs: 1_500,
                confidence: 0.93
            )
        ]

        let segments = RealtimeTranscriptSegmentFinalizer.finalizedSegments(
            providerSegments: providerSegments,
            liveTranscript: "send the report to",
            liveSpeaker: nil,
            durationSeconds: 2,
            didFinalize: false
        )

        XCTAssertEqual(segments.map(\.text), ["send the report"])
        XCTAssertEqual(segments.first?.endMs, 1_500)
    }

    func testCreatesLiveSegmentWhenProviderReturnedNoSegments() {
        let segments = RealtimeTranscriptSegmentFinalizer.finalizedSegments(
            providerSegments: [],
            liveTranscript: "only live text survived",
            liveSpeaker: "speaker_1",
            durationSeconds: 4,
            didFinalize: false
        )

        XCTAssertEqual(segments.map(\.text), ["only live text survived"])
        XCTAssertEqual(segments.first?.speaker, "speaker_1")
        XCTAssertEqual(segments.first?.startMs, 3_000)
        XCTAssertEqual(segments.first?.endMs, 4_000)
    }

    func testPreservesProviderSegmentsWhenFullerLiveTranscriptWouldCollapseMultipleSpeakers() {
        let providerSegments = [
            LiveTranscriptSegment(
                text: "can you review this",
                speaker: "speaker_0",
                isFinal: true,
                startMs: 900,
                endMs: 2_100,
                confidence: 0.9
            ),
            LiveTranscriptSegment(
                text: "yes today",
                speaker: "speaker_1",
                isFinal: true,
                startMs: 2_200,
                endMs: 3_100,
                confidence: 0.91
            )
        ]

        let segments = RealtimeTranscriptSegmentFinalizer.finalizedSegments(
            providerSegments: providerSegments,
            liveTranscript: "alex can you review this yes today",
            liveSpeaker: nil,
            durationSeconds: 4,
            didFinalize: true
        )

        XCTAssertEqual(segments.map(\.text), ["can you review this", "yes today"])
        XCTAssertEqual(segments.map(\.speaker), ["speaker_0", "speaker_1"])
    }
}
