import XCTest

final class OnboardingPermissionUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testOnboardingPermissionSlideShowsGrantControlsForBothDictationPermissions() throws {
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

        let primaryActionButton = app.buttons.matching(identifier: "onboarding-get-started-button").firstMatch
        XCTAssertTrue(waitForElement(primaryActionButton, in: app, timeout: 5))
        XCTAssertEqual(primaryActionButton.label, "Open Settings")

        XCTAssertTrue(app.staticTexts["Give WaiComputer permissions"].exists)
        XCTAssertTrue(waitForElement(app.staticTexts["Microphone"], in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.staticTexts["Accessibility"], in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "onboarding-permission-microphone-grant").firstMatch, in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "onboarding-permission-accessibility-grant").firstMatch, in: app, timeout: 3))
        // Input Monitoring is no longer required — the global hotkey monitor
        // uses NSEvent.addGlobalMonitorForEvents which is governed by the same
        // Accessibility TCC service as ⌘V paste.
        XCTAssertFalse(app.buttons.matching(identifier: "onboarding-permission-input-monitoring-grant").firstMatch.exists)
        XCTAssertFalse(app.buttons.matching(identifier: "onboarding-permission-automatic-paste-grant").firstMatch.exists)
    }

    @MainActor
    func testLegacyCompletedOnboardingFlagDoesNotSkipUpdatedPermissionOnboarding() throws {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["WAI_MOCK_DICTATION_PERMISSIONS"] = "missing"
        app.launchArguments = [
            "-nativeOnboardingV2Completed", "YES",
            "-nativeOnboardingV3Completed", "NO",
        ]
        app.launch()
        app.activate()

        XCTAssertTrue(waitForElement(app.staticTexts["Your AI second brain for voice."], in: app, timeout: 8))
        XCTAssertFalse(app.textFields["Email"].exists, "Legacy onboarding completion must not route first to auth")
    }

    @MainActor
    func testOnboardingResumesPersistedPermissionStepAfterRestart() throws {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["WAI_FORCE_ONBOARDING"] = "1"
        app.launchEnvironment["WAI_MOCK_DICTATION_PERMISSIONS"] = "needs_restart_accessibility"
        app.launchArguments = [
            "-nativeOnboardingV3CurrentPage", "4",
            "-nativeOnboardingV3Completed", "NO",
        ]
        app.launch()
        app.activate()

        XCTAssertTrue(waitForElement(app.staticTexts["Give WaiComputer permissions"], in: app, timeout: 8))
        XCTAssertTrue(waitForElement(app.staticTexts["Accessibility"], in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.descendants(matching: .any).matching(identifier: "onboarding-permission-accessibility-restart-required").firstMatch, in: app, timeout: 3))
        XCTAssertFalse(app.staticTexts["Your AI second brain for voice."].exists)
    }

    @MainActor
    func testOnboardingShowsRestartRequiredForAccessibilityPermissionRefresh() throws {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["WAI_FORCE_ONBOARDING"] = "1"
        app.launchEnvironment["WAI_MOCK_DICTATION_PERMISSIONS"] = "needs_restart_accessibility"
        app.launch()
        app.activate()

        XCTAssertTrue(waitForElement(app.staticTexts["Your AI second brain for voice."], in: app, timeout: 8))

        let continueButton = app.buttons.matching(identifier: "onboarding-continue-button").firstMatch
        for _ in 0..<4 {
            XCTAssertTrue(waitForElement(continueButton, in: app, timeout: 3))
            continueButton.tap()
        }

        XCTAssertTrue(waitForElement(app.descendants(matching: .any).matching(identifier: "onboarding-permission-accessibility-restart-required").firstMatch, in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "onboarding-permission-accessibility-restart").firstMatch, in: app, timeout: 3))
        XCTAssertFalse(app.buttons.matching(identifier: "onboarding-permission-accessibility-grant").firstMatch.exists)
        XCTAssertFalse(app.buttons.matching(identifier: "onboarding-permission-microphone-grant").firstMatch.exists)

        let primaryButton = app.buttons.matching(identifier: "onboarding-get-started-button").firstMatch
        XCTAssertTrue(waitForElement(primaryButton, in: app, timeout: 3))
        XCTAssertEqual(primaryButton.label, "Restart WaiComputer")
    }

    private func waitForElement(_ element: XCUIElement, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let exists = element.waitForExistence(timeout: timeout)
        if !exists {
            XCTFail("Element not found. App hierarchy:\n\(app.debugDescription)")
        }
        return exists
    }
}
