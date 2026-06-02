import XCTest

@testable import WaiComputerKit

final class DesktopSafetyPolicyTests: XCTestCase {
    private let policy = DesktopSafetyPolicy(
        ownBundleId: "is.waiwai.computer",
        blockedBundleIds: ["com.apple.Terminal"]
    )

    func testOwnUIExcluded() {
        let decision = policy.decide(
            DesktopCommandRequest(verb: "click", bundleId: "is.waiwai.computer")
        )
        XCTAssertFalse(decision.isAllowed)
        if case .refuse(let reason) = decision {
            XCTAssertTrue(reason.contains("own UI"))
        } else {
            XCTFail("expected refuse for own UI")
        }
    }

    func testBlockedAppRefused() {
        XCTAssertFalse(
            policy.decide(
                DesktopCommandRequest(verb: "type", bundleId: "com.apple.Terminal")
            ).isAllowed
        )
    }

    func testRefusedVerbsRegardlessOfApp() {
        XCTAssertFalse(
            policy.decide(
                DesktopCommandRequest(verb: "delete", bundleId: "com.apple.Mail")
            ).isAllowed
        )
        // Case-insensitive.
        XCTAssertFalse(
            policy.decide(
                DesktopCommandRequest(verb: "PURCHASE", bundleId: "com.apple.Mail")
            ).isAllowed
        )
    }

    func testAllowsSafeActions() {
        XCTAssertTrue(
            policy.decide(
                DesktopCommandRequest(verb: "open", bundleId: "com.apple.Mail")
            ).isAllowed
        )
        // A URL/file open has no target bundle.
        XCTAssertTrue(
            policy.decide(DesktopCommandRequest(verb: "click", bundleId: nil)).isAllowed
        )
    }
}
