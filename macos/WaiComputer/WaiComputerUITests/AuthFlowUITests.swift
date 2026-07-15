import XCTest

final class AuthFlowUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        try requireForegroundXCUITestOptIn()
    }

    private func launchAuthApp() -> XCUIApplication {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "auth_flow",
            skipOnboarding: true
        )
        app.launch()
        app.activate()
        return app
    }

    // MARK: - Auth

    @MainActor
    func testLoginScreenAppears() throws {
        let app = launchAuthApp()

        // Email text field (found by placeholder text)
        let emailField = app.textFields["Email"]
        XCTAssertTrue(emailField.waitForExistence(timeout: 8), "Email field should exist")

        XCTAssertTrue(
            app.buttons["auth-telegram-button"].waitForExistence(timeout: 3),
            "Telegram should be available from the first auth screen"
        )
        XCTAssertFalse(app.secureTextFields["Password"].exists, "Password is a secondary path")

        let submitButton = app.buttons.matching(identifier: "auth-submit-button").firstMatch
        XCTAssertTrue(submitButton.waitForExistence(timeout: 3), "Submit button should exist")
    }

    @MainActor
    func testLoginFormValidationButtonDisabledWhenEmpty() throws {
        let app = launchAuthApp()

        // Wait for auth form to load
        let emailField = app.textFields["Email"]
        XCTAssertTrue(emailField.waitForExistence(timeout: 8), "Email field should exist")

        // Submit button should be disabled when form fields are empty
        let submitButton = app.buttons.matching(identifier: "auth-submit-button").firstMatch
        XCTAssertTrue(submitButton.waitForExistence(timeout: 3), "Submit button should exist")
        XCTAssertFalse(submitButton.isEnabled, "Submit button should be disabled when form is empty")
    }

    @MainActor
    func testUnauthenticatedLaunchShowsAuthBeforeOnboarding() throws {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "auth_flow",
            forceOnboarding: true
        )
        app.launch()
        app.activate()

        XCTAssertTrue(app.textFields["Email"].waitForExistence(timeout: 8), "Users should create or restore their account before device setup")
        XCTAssertFalse(app.staticTexts["Welcome to WaiComputer"].exists, "Local device setup follows account creation")
        XCTAssertFalse(app.staticTexts["Try dictation now"].exists, "The dictation sandbox requires an authenticated, configured DictationManager")
    }
}
