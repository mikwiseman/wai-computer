import XCTest
@testable import WaiComputerKit

final class DictationFinalTranscriptSelectorTests: XCTestCase {
    func testCaptureLiveCandidateKeepsStartupWordsAfterShorterFinal() {
        let interim = DictationFinalTranscriptSelector.captureLiveCandidate(
            liveTranscript: "today we check fast startup",
            previousCandidate: nil
        )
        let final = DictationFinalTranscriptSelector.captureLiveCandidate(
            liveTranscript: "check fast startup",
            previousCandidate: interim
        )

        XCTAssertEqual(final, "today we check fast startup")
    }

    func testCaptureLiveCandidateDropsCorrectedInterimTail() {
        let interim = DictationFinalTranscriptSelector.captureLiveCandidate(
            liveTranscript: "send the report to",
            previousCandidate: nil
        )
        let final = DictationFinalTranscriptSelector.captureLiveCandidate(
            liveTranscript: "send the report",
            previousCandidate: interim
        )

        XCTAssertEqual(final, "send the report")
    }

    func testKeepsActiveTrailingInterimWhenProviderCloseDidNotReemitIt() {
        let selected = DictationFinalTranscriptSelector.select(
            providerTranscript: "hello world how are",
            liveTranscript: "hello world how are you",
            liveTranscriptCandidate: nil,
            hasActiveInterim: true
        )

        XCTAssertEqual(selected, "hello world how are you")
    }

    func testRecoversStartupWordsFromCachedLiveCandidateAfterShorterFinal() {
        let selected = DictationFinalTranscriptSelector.select(
            providerTranscript: "check fast startup",
            liveTranscript: "check fast startup",
            liveTranscriptCandidate: "today we check fast startup",
            hasActiveInterim: false
        )

        XCTAssertEqual(selected, "today we check fast startup")
    }

    func testKeepsCommittedLiveTailWhenProviderCloseReturnedShorterFinal() {
        let selected = DictationFinalTranscriptSelector.select(
            providerTranscript: "send the report",
            liveTranscript: "send the report today",
            liveTranscriptCandidate: "send the report today",
            hasActiveInterim: false
        )

        XCTAssertEqual(selected, "send the report today")
    }

    func testDropsStaleInterimTailAfterProviderFinalCorrectsIt() {
        let selected = DictationFinalTranscriptSelector.select(
            providerTranscript: "send the report",
            liveTranscript: "send the report",
            liveTranscriptCandidate: "send the report to",
            hasActiveInterim: false
        )

        XCTAssertEqual(selected, "send the report")
    }

    func testDropsStaleInterimWhenItOnlyContainsFinalAsWordPrefix() {
        let selected = DictationFinalTranscriptSelector.select(
            providerTranscript: "open app",
            liveTranscript: "open app",
            liveTranscriptCandidate: "open apple settings",
            hasActiveInterim: false
        )

        XCTAssertEqual(selected, "open app")
    }
}
