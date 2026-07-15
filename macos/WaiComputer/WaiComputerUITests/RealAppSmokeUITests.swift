import XCTest

final class RealAppSmokeUITests: XCTestCase {
    private let productionBundleIdentifier = "is.waiwai.computer"

    override func setUpWithError() throws {
        continueAfterFailure = false
        try requireForegroundXCUITestOptIn()
    }

    private func installedReleaseApp() throws -> XCUIApplication {
        let appURL = URL(fileURLWithPath: "/Applications/WaiComputer.app")
        guard FileManager.default.fileExists(atPath: appURL.path) else {
            throw XCTSkip("Installed WaiComputer release app is not present at /Applications/WaiComputer.app")
        }

        let infoURL = appURL.appendingPathComponent("Contents/Info.plist")
        let infoData = try Data(contentsOf: infoURL)
        let plist = try PropertyListSerialization.propertyList(
            from: infoData,
            options: [],
            format: nil
        ) as? [String: Any]
        XCTAssertEqual(plist?["CFBundleIdentifier"] as? String, productionBundleIdentifier)

        return XCUIApplication(bundleIdentifier: productionBundleIdentifier)
    }

    @MainActor
    func testInstalledReleaseShowsAuthBeforePersistedTryPageWithoutSession() throws {
        let app = try installedReleaseApp()
        app.terminate()
        app.launchEnvironment["WAI_DISABLE_STORED_SESSION_RESTORE"] = "1"
        app.launchArguments = [
            "-ApplePersistenceIgnoreState", "YES",
            "-nativeOnboardingV4Completed", "NO",
            "-nativeOnboardingV4CurrentPage", "5",
        ]
        app.launch()
        app.activate()

        XCTAssertTrue(
            app.textFields["Email"].waitForExistence(timeout: 8),
            "Installed release should show the account gateway before device setup."
        )
        XCTAssertFalse(app.staticTexts["Welcome to WaiComputer"].exists)
        XCTAssertFalse(
            app.staticTexts["Try dictation now"].exists,
            "The dictation sandbox requires an authenticated, configured DictationManager."
        )

        app.terminate()
    }

    @MainActor
    func testInstalledReleaseIgnoresLegacyOnboardingCompletionWithoutSession() throws {
        let app = try installedReleaseApp()
        app.terminate()
        app.launchEnvironment["WAI_DISABLE_STORED_SESSION_RESTORE"] = "1"
        app.launchArguments = [
            "-ApplePersistenceIgnoreState", "YES",
            "-nativeOnboardingV2Completed", "YES",
            "-nativeOnboardingV3Completed", "YES",
            "-nativeOnboardingV4Completed", "NO",
        ]
        app.launch()
        app.activate()

        XCTAssertTrue(
            app.textFields["Email"].waitForExistence(timeout: 8),
            "Legacy onboarding flags must not bypass auth in the installed release."
        )
        XCTAssertFalse(app.staticTexts["Welcome to WaiComputer"].exists)

        app.terminate()
    }
}
