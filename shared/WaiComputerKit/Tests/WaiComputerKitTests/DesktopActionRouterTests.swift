import Foundation
import XCTest

@testable import WaiComputerKit

final class DesktopActionRouterTests: XCTestCase {
    private let router = DesktopActionRouter(
        safety: DesktopSafetyPolicy(ownBundleId: "is.waiwai.computer")
    )

    func testOpenMailtoBecomesOpenURL() {
        let plan = router.plan(
            tool: "desktop_open",
            args: ["target": .string("mailto:a@x.com?subject=Hi")]
        )
        guard case .openURL(let url) = plan else { return XCTFail("expected openURL") }
        XCTAssertEqual(url.scheme, "mailto")
    }

    func testOpenHTTPSBecomesOpenURL() {
        let plan = router.plan(
            tool: "desktop_open", args: ["target": .string("https://wai.computer")]
        )
        if case .openURL(let url) = plan {
            XCTAssertEqual(url.host, "wai.computer")
        } else {
            XCTFail("expected openURL")
        }
    }

    func testOpenBareNameBecomesOpenApp() {
        let plan = router.plan(tool: "desktop_open", args: ["target": .string("Mail")])
        XCTAssertEqual(plan, .openApp(name: "Mail"))
    }

    func testOpenDisallowedSchemeRefused() {
        let plan = router.plan(
            tool: "desktop_open",
            args: ["target": .string("javascript:alert(1)")]
        )
        XCTAssertTrue(plan.isRefusal)
    }

    func testOpenMissingTargetRefused() {
        XCTAssertTrue(router.plan(tool: "desktop_open", args: [:]).isRefusal)
        XCTAssertTrue(
            router.plan(tool: "desktop_open", args: ["target": .string("  ")]).isRefusal
        )
    }

    func testTypeBecomesTypeText() {
        let plan = router.plan(tool: "desktop_type", args: ["text": .string("hello")])
        XCTAssertEqual(plan, .typeText("hello"))
    }

    func testTypeMissingTextRefused() {
        XCTAssertTrue(router.plan(tool: "desktop_type", args: [:]).isRefusal)
        XCTAssertTrue(
            router.plan(tool: "desktop_type", args: ["text": .string("")]).isRefusal
        )
    }

    func testClickAcceptsIntAndDoubleIndex() {
        XCTAssertEqual(
            router.plan(tool: "desktop_click", args: ["index": .int(3)]), .click(index: 3)
        )
        XCTAssertEqual(
            router.plan(tool: "desktop_click", args: ["index": .double(4)]),
            .click(index: 4)
        )
    }

    func testClickMissingIndexRefused() {
        XCTAssertTrue(router.plan(tool: "desktop_click", args: [:]).isRefusal)
    }

    func testSnapshotToolPlansSnapshot() {
        XCTAssertEqual(router.plan(tool: "desktop_snapshot", args: [:]), .snapshot)
    }

    func testUnknownToolRefused() {
        XCTAssertTrue(router.plan(tool: "desktop_launch_missiles", args: [:]).isRefusal)
    }

    func testSafetyPolicyVerbRefusalPropagates() {
        // A policy that refuses the "type" verb must block desktop_type at the router.
        let strict = DesktopActionRouter(
            safety: DesktopSafetyPolicy(ownBundleId: "is.waiwai.computer", refusedVerbs: ["type"])
        )
        XCTAssertTrue(
            strict.plan(tool: "desktop_type", args: ["text": .string("x")]).isRefusal
        )
    }
}
