import XCTest
@testable import WaiComputerKit

final class RealtimeTranscriptCandidateSelectorTests: XCTestCase {
    func testPrefersLongerCandidateWhenProviderFinalDroppedStartupWords() {
        let selected = RealtimeTranscriptCandidateSelector.select([
            "check fast startup",
            nil,
            "today we check fast startup",
        ])

        XCTAssertEqual(selected, "today we check fast startup")
    }

    func testKeepsProviderCandidateWhenItIsAtLeastAsCompleteAsInterim() {
        let selected = RealtimeTranscriptCandidateSelector.select([
            "hello world",
            nil,
            "hello wor",
        ])

        XCTAssertEqual(selected, "hello world")
    }

    func testKeepsProviderCandidateWhenInterimOnlyAddsRepeatedTail() {
        let selected = RealtimeTranscriptCandidateSelector.select([
            "please ship this today",
            "please ship this today please ship",
        ])

        XCTAssertEqual(selected, "please ship this today")
    }

    func testKeepsProviderCandidateWhenInterimOnlyAppendsUnfinalizedTail() {
        let selected = RealtimeTranscriptCandidateSelector.select([
            "send the report",
            "send the report to",
        ])

        XCTAssertEqual(selected, "send the report")
    }

    func testDoesNotPreferUnrelatedLongerCandidate() {
        let selected = RealtimeTranscriptCandidateSelector.select([
            "hello world",
            nil,
            "unrelated longer partial transcript",
        ])

        XCTAssertEqual(selected, "hello world")
    }

    func testPrefersFullerCandidateWhenPunctuationBreaksLiteralContainment() {
        let selected = RealtimeTranscriptCandidateSelector.select([
            "send OpenAI Codex logs",
            "please send OpenAI, Codex logs",
        ])

        XCTAssertEqual(selected, "please send OpenAI, Codex logs")
    }

    func testDoesNotPreferLongerCandidateThatOnlyContainsFinalAsWordPrefix() {
        let selected = RealtimeTranscriptCandidateSelector.select([
            "open app",
            "open apple settings",
        ])

        XCTAssertEqual(selected, "open app")
    }

    func testDoesNotPreferLongerCandidateWithOnlyNonContiguousTokenOverlap() {
        let selected = RealtimeTranscriptCandidateSelector.select([
            "hello world",
            "hello unrelated world transcript",
        ])

        XCTAssertEqual(selected, "hello world")
    }

    func testIgnoresEmptyCandidates() {
        let selected = RealtimeTranscriptCandidateSelector.select([
            "   ",
            nil,
            "\nfirst word retained\n",
        ])

        XCTAssertEqual(selected, "first word retained")
    }
}
