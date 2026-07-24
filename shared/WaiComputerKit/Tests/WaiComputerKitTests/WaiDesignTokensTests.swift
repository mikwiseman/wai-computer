import XCTest
@testable import WaiComputerKit

final class WaiDesignTokensTests: XCTestCase {
    func testSpacingUsesOneSharedEightPointRhythm() {
        XCTAssertEqual(WaiDesignTokens.Spacing.xxs, 2)
        XCTAssertEqual(WaiDesignTokens.Spacing.xs, 4)
        XCTAssertEqual(WaiDesignTokens.Spacing.sm, 8)
        XCTAssertEqual(WaiDesignTokens.Spacing.md, 12)
        XCTAssertEqual(WaiDesignTokens.Spacing.lg, 16)
        XCTAssertEqual(WaiDesignTokens.Spacing.xl, 24)
        XCTAssertEqual(WaiDesignTokens.Spacing.xxl, 32)
        XCTAssertEqual(WaiDesignTokens.Spacing.xxxl, 48)
        XCTAssertEqual(WaiDesignTokens.Spacing.huge, 64)
    }

    func testRadiiFormAConcentricHierarchy() {
        let radii = [
            WaiDesignTokens.Radius.sm,
            WaiDesignTokens.Radius.md,
            WaiDesignTokens.Radius.lg,
            WaiDesignTokens.Radius.xl,
            WaiDesignTokens.Radius.xxl,
        ]

        XCTAssertEqual(radii, [8, 12, 16, 22, 28])
        XCTAssertEqual(radii, radii.sorted())
    }

    func testControlMetricsProtectReadableTouchTargets() {
        XCTAssertEqual(WaiDesignTokens.Control.compactHeight, 32)
        XCTAssertEqual(WaiDesignTokens.Control.regularHeight, 44)
        XCTAssertEqual(WaiDesignTokens.Control.largeHeight, 52)
        XCTAssertGreaterThanOrEqual(WaiDesignTokens.Control.regularHeight, 44)
    }

    func testMotionDurationsShareOneDeliberateScale() {
        XCTAssertEqual(WaiDesignTokens.Motion.quick, 0.16)
        XCTAssertEqual(WaiDesignTokens.Motion.standard, 0.25)
        XCTAssertEqual(WaiDesignTokens.Motion.emphasized, 0.35)
        XCTAssertLessThan(WaiDesignTokens.Motion.quick, WaiDesignTokens.Motion.standard)
        XCTAssertLessThan(WaiDesignTokens.Motion.standard, WaiDesignTokens.Motion.emphasized)
    }
}
