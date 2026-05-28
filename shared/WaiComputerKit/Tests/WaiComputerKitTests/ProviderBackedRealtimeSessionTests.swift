import XCTest
@testable import WaiComputerKit

final class ProviderBackedRealtimeSessionDominantSpeakerTests: XCTestCase {
    func testReturnsNilWhenWordsArrayMissing() {
        let alternative: [String: Any] = ["transcript": "hello", "confidence": 0.9]
        XCTAssertNil(ProviderBackedRealtimeSession.dominantSpeakerLabel(in: alternative))
    }

    func testReturnsNilWhenWordsHaveNoSpeakerTags() {
        let alternative: [String: Any] = [
            "words": [
                ["word": "hello", "start": 0.0, "end": 0.4],
                ["word": "world", "start": 0.4, "end": 0.8],
            ]
        ]
        XCTAssertNil(ProviderBackedRealtimeSession.dominantSpeakerLabel(in: alternative))
    }

    func testPicksSingleSpeakerLabel() {
        let alternative: [String: Any] = [
            "words": [
                ["word": "hi", "start": 0.0, "end": 0.3, "speaker": 0],
                ["word": "there", "start": 0.3, "end": 0.7, "speaker": 0],
            ]
        ]
        XCTAssertEqual(
            ProviderBackedRealtimeSession.dominantSpeakerLabel(in: alternative),
            "speaker_0"
        )
    }

    func testPicksDominantSpeakerByDuration() {
        // speaker 1 holds the floor longer even though speaker 0 has more words.
        let alternative: [String: Any] = [
            "words": [
                ["word": "yes", "start": 0.0, "end": 0.2, "speaker": 0],
                ["word": "ok", "start": 0.2, "end": 0.3, "speaker": 0],
                ["word": "let-me-explain", "start": 0.3, "end": 2.5, "speaker": 1],
            ]
        ]
        XCTAssertEqual(
            ProviderBackedRealtimeSession.dominantSpeakerLabel(in: alternative),
            "speaker_1"
        )
    }

    func testIgnoresWordsWithNonIntegerSpeaker() {
        let alternative: [String: Any] = [
            "words": [
                ["word": "noise", "start": 0.0, "end": 0.1, "speaker": "weird"],
                ["word": "hello", "start": 0.1, "end": 0.5, "speaker": 2],
            ]
        ]
        XCTAssertEqual(
            ProviderBackedRealtimeSession.dominantSpeakerLabel(in: alternative),
            "speaker_2"
        )
    }

    func testIgnoresNegativeSpeakerSentinel() {
        // Some providers emit `-1` for "uncertain". Treat as no signal.
        let alternative: [String: Any] = [
            "words": [
                ["word": "uh", "start": 0.0, "end": 0.4, "speaker": -1],
                ["word": "ok", "start": 0.4, "end": 0.6, "speaker": 3],
            ]
        ]
        XCTAssertEqual(
            DeepgramSpeakerLabel.dominant(in: alternative),
            "speaker_3"
        )
    }

    func testSharedHelperMatchesLegacyShim() {
        // ProviderBackedRealtimeSession.dominantSpeakerLabel is now a thin
        // forward to DeepgramSpeakerLabel — pin parity so the two never drift.
        let alternative: [String: Any] = [
            "words": [
                ["word": "hi", "start": 0.0, "end": 0.5, "speaker": 5],
            ]
        ]
        XCTAssertEqual(
            ProviderBackedRealtimeSession.dominantSpeakerLabel(in: alternative),
            DeepgramSpeakerLabel.dominant(in: alternative)
        )
    }
}
