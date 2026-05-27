import Foundation
import XCTest
@testable import WaiComputerKit

final class InworldProviderSessionTests: XCTestCase {

    // MARK: - cappedKeyTerms

    func testCappedKeyTermsRespectsCharBudget() {
        // Build a list whose total chars (incl join separators) exceeds the budget.
        let longTerm = String(repeating: "x", count: 50)  // 50 chars + 1 sep = 51 each
        let many = (1...300).map { _ in longTerm }
        let output = InworldProviderSession.cappedKeyTerms(many)
        let totalChars = output.reduce(0) { $0 + $1.count + 1 }
        XCTAssertLessThanOrEqual(totalChars, InworldProviderSession.promptContextCharBudget + 60)
        XCTAssertGreaterThan(output.count, 0)
    }

    func testCappedKeyTermsTruncatesEntriesPastTermLimit() {
        let huge = String(repeating: "z", count: 200)
        let output = InworldProviderSession.cappedKeyTerms([huge])
        XCTAssertEqual(output.first?.count, InworldProviderSession.promptTermCharLimit)
    }

    func testCappedKeyTermsDeDuplicatesCaseInsensitive() {
        let output = InworldProviderSession.cappedKeyTerms([
            "WaiComputer", "waicomputer", "WAICOMPUTER", "  waicomputer\t", "Anthropic",
        ])
        XCTAssertEqual(output, ["WaiComputer", "Anthropic"])
    }

    func testCappedKeyTermsDropsEmptiesAndWhitespace() {
        let output = InworldProviderSession.cappedKeyTerms(["", "  ", "\n", "Real"])
        XCTAssertEqual(output, ["Real"])
    }

    func testApplyPromptHintsUsesInworldPromptsField() {
        var transcribeConfig: [String: Any] = ["modelId": "inworld/inworld-stt-1"]

        InworldProviderSession.applyPromptHints(
            from: ["  WaiComputer  ", "waicomputer", "Anthropic"],
            to: &transcribeConfig
        )

        XCTAssertEqual(transcribeConfig["prompts"] as? [String], ["WaiComputer", "Anthropic"])
        XCTAssertNil(transcribeConfig["context"])
    }

    func testSafeReceivedTextFrameSummaryDoesNotExposeTranscriptText() {
        let payload = """
        {
          "transcription": {
            "transcript": "Private words from a dictated sentence",
            "is_final": true
          }
        }
        """

        let summary = InworldProviderSession.safeReceivedTextFrameSummary(payload)

        XCTAssertFalse(summary.contains("Private words"))
        XCTAssertFalse(summary.contains("dictated sentence"))
        XCTAssertTrue(summary.contains("transcription"))
        XCTAssertTrue(summary.contains("chars=38"))
        XCTAssertTrue(summary.contains("final=true"))
    }
}
