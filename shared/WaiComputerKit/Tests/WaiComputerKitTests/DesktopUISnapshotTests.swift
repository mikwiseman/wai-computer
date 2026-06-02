import Foundation
import XCTest

@testable import WaiComputerKit

final class DesktopUISnapshotTests: XCTestCase {
    private let snapshot = DesktopUISnapshot(
        app: "Mail",
        elements: [
            DesktopUIElement(index: 0, role: "AXButton", title: "Send", actionable: true),
            DesktopUIElement(index: 1, role: "AXStaticText", title: "Draft", actionable: false),
            DesktopUIElement(
                index: 2, role: "AXTextField", title: "  To  ", actionable: true
            ),
        ]
    )

    func testElementAtIndexInRange() {
        XCTAssertEqual(snapshot.element(at: 0)?.title, "Send")
        XCTAssertEqual(snapshot.element(at: 2)?.role, "AXTextField")
    }

    func testElementAtIndexOutOfRangeIsNil() {
        XCTAssertNil(snapshot.element(at: -1))
        XCTAssertNil(snapshot.element(at: 3))
    }

    func testModelDigestActionableOnlyByDefault() {
        let digest = snapshot.modelDigest()
        // The non-actionable static text is excluded.
        XCTAssertFalse(digest.contains("AXStaticText"))
        XCTAssertTrue(digest.contains("0: AXButton \"Send\""))
        // Title is trimmed.
        XCTAssertTrue(digest.contains("2: AXTextField \"To\""))
    }

    func testModelDigestIncludesNonActionableWhenAsked() {
        let digest = snapshot.modelDigest(actionableOnly: false)
        XCTAssertTrue(digest.contains("1: AXStaticText \"Draft\""))
    }

    func testModelDigestTruncatesLongTitles() {
        let long = DesktopUISnapshot(elements: [
            DesktopUIElement(
                index: 0, role: "AXButton", title: String(repeating: "x", count: 200),
                actionable: true
            )
        ])
        let digest = long.modelDigest(maxTitleLength: 10)
        XCTAssertTrue(digest.contains("…"))
        XCTAssertLessThan(digest.count, 40)
    }

    func testEmptyTitleOmitsQuotes() {
        let s = DesktopUISnapshot(elements: [
            DesktopUIElement(index: 0, role: "AXButton", title: "", actionable: true)
        ])
        XCTAssertEqual(s.modelDigest(), "0: AXButton")
    }

    func testCodableRoundTrip() throws {
        let data = try JSONEncoder().encode(snapshot)
        let decoded = try JSONDecoder().decode(DesktopUISnapshot.self, from: data)
        XCTAssertEqual(decoded, snapshot)
    }
}
