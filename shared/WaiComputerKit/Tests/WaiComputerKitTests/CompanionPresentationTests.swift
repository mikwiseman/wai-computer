import XCTest
@testable import WaiComputerKit

final class CompanionPresentationTests: XCTestCase {
    func testUntitledChatLabelUsesLocalizedDateFallback() {
        let created = Date(timeIntervalSince1970: 1_768_545_600) // 2026-01-14T00:00:00Z
        let label = CompanionChatPresentation.chatLabel(
            title: nil,
            createdAt: created,
            lastMessageAt: nil,
            locale: Locale(identifier: "ru_RU")
        )

        XCTAssertTrue(label.hasPrefix("Чат · "))
        XCTAssertFalse(label.contains("Untitled"))
    }

    func testChatLabelUsesNonEmptyServerTitle() {
        let created = Date(timeIntervalSince1970: 1_768_545_600)
        let label = CompanionChatPresentation.chatLabel(
            title: "   Pricing follow-ups   ",
            createdAt: created,
            lastMessageAt: nil,
            locale: Locale(identifier: "en_US")
        )

        XCTAssertEqual(label, "Pricing follow-ups")
    }

    func testComposerMetricsKeepPlaceholderAndEditorInsetsAligned() {
        XCTAssertEqual(
            CompanionComposerMetrics.textInsets,
            CompanionComposerMetrics.placeholderInsets
        )
        XCTAssertGreaterThanOrEqual(CompanionComposerMetrics.minHeight, 44)
        XCTAssertGreaterThan(
            CompanionComposerMetrics.maxHeight,
            CompanionComposerMetrics.minHeight
        )
    }
}
