import XCTest

final class OnboardingPermissionUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testAppStoreOnboardingPermissionSlideShowsGrantControls() throws {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["WAI_FORCE_ONBOARDING"] = "1"
        app.launchEnvironment["WAI_MOCK_DICTATION_PERMISSIONS"] = "missing"
        app.launch()
        app.activate()

        XCTAssertTrue(waitForElement(app.staticTexts["Your AI second brain for voice."], in: app, timeout: 8))

        let continueButton = app.buttons.matching(identifier: "onboarding-continue-button").firstMatch
        for _ in 0..<4 {
            XCTAssertTrue(waitForElement(continueButton, in: app, timeout: 3))
            continueButton.tap()
        }

        let grantMissingButton = app.buttons.matching(identifier: "onboarding-get-started-button").firstMatch
        XCTAssertTrue(waitForElement(grantMissingButton, in: app, timeout: 5))
        XCTAssertEqual(grantMissingButton.label, "Grant Missing")

        XCTAssertTrue(app.staticTexts["Set up voice access."].exists)
        let appStoreManualPasteText = app.staticTexts
            .matching(NSPredicate(format: "label CONTAINS[c] %@ OR value CONTAINS[c] %@", "manual paste", "manual paste"))
            .firstMatch
        XCTAssertTrue(waitForElement(appStoreManualPasteText, in: app, timeout: 3))

        XCTAssertTrue(waitForElement(app.staticTexts["Microphone"], in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.staticTexts["Input Monitoring"], in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "onboarding-permission-microphone-grant").firstMatch, in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "onboarding-permission-input-monitoring-grant").firstMatch, in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "onboarding-permission-input-monitoring-settings").firstMatch, in: app, timeout: 3))
        XCTAssertFalse(app.staticTexts["Automatic Paste"].exists)
    }

    private func waitForElement(_ element: XCUIElement, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let exists = element.waitForExistence(timeout: timeout)
        if !exists {
            XCTFail("Element not found. App hierarchy:\n\(app.debugDescription)")
        }
        return exists
    }
}
