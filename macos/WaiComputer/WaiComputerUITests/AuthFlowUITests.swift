import XCTest

final class AuthFlowUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
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

        // Password secure field (found by placeholder text)
        let passwordField = app.secureTextFields["Password"]
        XCTAssertTrue(passwordField.waitForExistence(timeout: 3), "Password field should exist")

        // Submit button (found by accessibility identifier)
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

        XCTAssertTrue(app.textFields["Email"].waitForExistence(timeout: 8), "Unauthenticated users must sign in before the dictation onboarding tour")
        XCTAssertFalse(app.staticTexts["Try dictation now"].exists, "The dictation sandbox requires an authenticated, configured DictationManager")
    }
}
