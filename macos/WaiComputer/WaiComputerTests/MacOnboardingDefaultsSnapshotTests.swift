import XCTest

final class MacOnboardingDefaultsSnapshotTests: XCTestCase {
    private var suiteName: String!
    private var defaults: UserDefaults!

    override func setUpWithError() throws {
        try super.setUpWithError()
        suiteName = "MacOnboardingDefaultsSnapshotTests.\(UUID().uuidString)"
        defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defaults.removePersistentDomain(forName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        suiteName = nil
        super.tearDown()
    }

    func testSnapshotRestoresCompletedOnboardingAfterDefaultsDomainWipe() {
        defaults.set(true, forKey: "nativeOnboardingV4Completed")
        defaults.set(true, forKey: "nativeOnboardingV5PreAuthCompleted")
        defaults.set(true, forKey: "nativeOnboardingV5PostAuthCompleted.user-1")
        defaults.set(5, forKey: "nativeOnboardingV5PostAuthCurrentPage")
        defaults.set(true, forKey: "onboardingMicAcknowledged")
        defaults.set(true, forKey: "onboardingSystemAudioSetupCompleted")

        let snapshot = MacOnboardingDefaultsSnapshot.capture(
            defaults: defaults,
            userId: "user-1"
        )

        defaults.removePersistentDomain(forName: suiteName)
        snapshot.restore(to: defaults)

        XCTAssertTrue(defaults.bool(forKey: "nativeOnboardingV4Completed"))
        XCTAssertTrue(defaults.bool(forKey: "nativeOnboardingV5PreAuthCompleted"))
        XCTAssertTrue(defaults.bool(forKey: "nativeOnboardingV5PostAuthCompleted.user-1"))
        XCTAssertNil(defaults.object(forKey: "nativeOnboardingV5PostAuthCurrentPage"))
        XCTAssertTrue(defaults.bool(forKey: "onboardingMicAcknowledged"))
        XCTAssertTrue(defaults.bool(forKey: "onboardingSystemAudioSetupCompleted"))
    }

    func testSnapshotDoesNotInventOnboardingCompletion() {
        let snapshot = MacOnboardingDefaultsSnapshot.capture(
            defaults: defaults,
            userId: "user-1"
        )

        defaults.removePersistentDomain(forName: suiteName)
        snapshot.restore(to: defaults)

        XCTAssertFalse(defaults.bool(forKey: "nativeOnboardingV4Completed"))
        XCTAssertFalse(defaults.bool(forKey: "nativeOnboardingV5PreAuthCompleted"))
        XCTAssertFalse(defaults.bool(forKey: "nativeOnboardingV5PostAuthCompleted.user-1"))
    }
}
