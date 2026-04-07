import XCTest

final class SettingsUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func launchToSettings() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["UITEST_SCENARIO"] = "main_view"
        app.launch()
        app.activate()

        // Wait for sidebar to load, then navigate to Settings
        let sidebar = app.descendants(matching: .any)
            .matching(identifier: "sidebar")
            .firstMatch
        _ = sidebar.waitForExistence(timeout: 8)

        let settingsButton = app.buttons.matching(identifier: "sidebar-settings").firstMatch
        _ = settingsButton.waitForExistence(timeout: 5)
        app.activate()
        settingsButton.tap()

        return app
    }

    private func waitForElement(_ element: XCUIElement, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let exists = element.waitForExistence(timeout: timeout)
        if !exists {
            XCTFail("Element not found. App hierarchy:\n\(app.debugDescription)")
        }
        return exists
    }

    // MARK: - Settings

    @MainActor
    func testSettingsViewElements() throws {
        let app = launchToSettings()

        // Account section header
        let accountHeader = app.descendants(matching: .any)
            .matching(identifier: "settings-account-header")
            .firstMatch
        XCTAssertTrue(waitForElement(accountHeader, in: app, timeout: 5))

        // Transcription section header
        let transcriptionHeader = app.descendants(matching: .any)
            .matching(identifier: "settings-transcription-header")
            .firstMatch
        XCTAssertTrue(waitForElement(transcriptionHeader, in: app, timeout: 3))

        // About section header
        let aboutHeader = app.descendants(matching: .any)
            .matching(identifier: "settings-about-header")
            .firstMatch
        XCTAssertTrue(waitForElement(aboutHeader, in: app, timeout: 3))

        // Sign out button
        let signOutButton = app.buttons.matching(identifier: "settings-sign-out-button").firstMatch
        XCTAssertTrue(waitForElement(signOutButton, in: app, timeout: 3))
    }

    @MainActor
    func testSignOutButtonExists() throws {
        let app = launchToSettings()

        // Sign out button should exist and be hittable
        let signOutButton = app.buttons.matching(identifier: "settings-sign-out-button").firstMatch
        XCTAssertTrue(waitForElement(signOutButton, in: app, timeout: 5))
        XCTAssertTrue(signOutButton.isEnabled, "Sign Out button should be enabled")
    }
}
