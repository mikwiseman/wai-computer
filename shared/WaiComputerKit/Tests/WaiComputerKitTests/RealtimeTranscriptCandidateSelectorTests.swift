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

    func testDoesNotPreferUnrelatedLongerCandidate() {
        let selected = RealtimeTranscriptCandidateSelector.select([
            "hello world",
            nil,
            "unrelated longer partial transcript",
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
