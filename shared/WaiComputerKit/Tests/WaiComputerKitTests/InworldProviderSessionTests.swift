import Foundation
import XCTest
@testable import WaiComputerKit

final class InworldProviderSessionTests: XCTestCase {

    // MARK: - cappedKeyTerms (Soniox v4 RT context budget)

    func testCappedKeyTermsRespectsCharBudget() {
        // Build a list whose total chars (incl join separators) exceeds the budget.
        let longTerm = String(repeating: "x", count: 50)  // 50 chars + 1 sep = 51 each
        let many = (1...300).map { _ in longTerm }
        let output = InworldProviderSession.cappedKeyTerms(many)
        let totalChars = output.reduce(0) { $0 + $1.count + 1 }
        XCTAssertLessThanOrEqual(totalChars, InworldProviderSession.sonioxContextCharBudget + 60)
        XCTAssertGreaterThan(output.count, 0)
    }

    func testCappedKeyTermsTruncatesEntriesPastTermLimit() {
        let huge = String(repeating: "z", count: 200)
        let output = InworldProviderSession.cappedKeyTerms([huge])
        XCTAssertEqual(output.first?.count, InworldProviderSession.sonioxTermCharLimit)
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
}
