import XCTest

final class OnboardingPermissionUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        try requireForegroundXCUITestOptIn()
    }

    @MainActor
    func testOnboardingPermissionSlideShowsGrantControlsForRequiredPermissions() throws {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "onboarding_flow",
            forceOnboarding: true,
            permissionMock: "missing",
            launchArguments: ["-waiUserLanguage", "en", "-nativeOnboardingV4CurrentPage", "2"]
        )
        app.launch()
        app.activate()

        let primaryActionButton = app.buttons.matching(identifier: "onboarding-get-started-button").firstMatch
        XCTAssertTrue(waitForElement(primaryActionButton, in: app, timeout: 5))
        XCTAssertEqual(primaryActionButton.label, "Open Microphone Settings")

        XCTAssertTrue(app.staticTexts["Give WaiComputer permissions"].exists)
        XCTAssertTrue(waitForElement(app.staticTexts["Microphone"], in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.staticTexts["Accessibility"], in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.staticTexts["System Audio"], in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "onboarding-permission-microphone-grant").firstMatch, in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "onboarding-permission-accessibility-grant").firstMatch, in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "onboarding-permission-system-audio-setup").firstMatch, in: app, timeout: 3))
        // Input Monitoring is no longer required — the global hotkey monitor
        // uses NSEvent.addGlobalMonitorForEvents which is governed by the same
        // Accessibility TCC service as ⌘V paste.
        XCTAssertFalse(app.buttons.matching(identifier: "onboarding-permission-input-monitoring-grant").firstMatch.exists)
        XCTAssertFalse(app.buttons.matching(identifier: "onboarding-permission-automatic-paste-grant").firstMatch.exists)
    }

    @MainActor
    func testOnboardingPermissionSlidePromptsFreshMicrophonePermissionBeforeSettings() throws {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "onboarding_flow",
            forceOnboarding: true,
            permissionMock: "missing_not_determined",
            launchArguments: ["-waiUserLanguage", "en", "-nativeOnboardingV4CurrentPage", "2"]
        )
        app.launch()
        app.activate()

        let primaryActionButton = app.buttons.matching(identifier: "onboarding-get-started-button").firstMatch
        XCTAssertTrue(waitForElement(primaryActionButton, in: app, timeout: 5))
        XCTAssertEqual(primaryActionButton.label, "Grant Microphone")

        let microphoneAction = app.buttons.matching(identifier: "onboarding-permission-microphone-grant").firstMatch
        XCTAssertTrue(waitForElement(microphoneAction, in: app, timeout: 3))
        XCTAssertEqual(microphoneAction.label, "Grant")
    }

    @MainActor
    func testLegacyCompletedOnboardingFlagDoesNotSkipUpdatedPermissionOnboarding() throws {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "onboarding_flow",
            forceOnboarding: true,
            permissionMock: "missing",
            launchArguments: [
                "-waiUserLanguage", "en",
                "-nativeOnboardingV4CurrentPage", "0",
                "-nativeOnboardingV2Completed", "YES",
                "-nativeOnboardingV3Completed", "YES",
                "-nativeOnboardingV4Completed", "NO",
            ]
        )
        app.launch()
        app.activate()

        XCTAssertTrue(waitForElement(app.staticTexts["Welcome to WaiComputer"], in: app, timeout: 8))
        XCTAssertFalse(app.textFields["Email"].exists, "Legacy onboarding completion must not route first to auth")
    }

    @MainActor
    func testOnboardingResumesPersistedPermissionStepAfterRestart() throws {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "onboarding_flow",
            forceOnboarding: true,
            permissionMock: "needs_restart_accessibility",
            launchArguments: [
                "-waiUserLanguage", "en",
                "-nativeOnboardingV4CurrentPage", "2",
                "-nativeOnboardingV4Completed", "NO",
            ]
        )
        app.launch()
        app.activate()

        XCTAssertTrue(waitForElement(app.staticTexts["Give WaiComputer permissions"], in: app, timeout: 8))
        XCTAssertTrue(waitForElement(app.staticTexts["Accessibility"], in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.descendants(matching: .any).matching(identifier: "onboarding-permission-accessibility-restart-required").firstMatch, in: app, timeout: 3))
        XCTAssertFalse(app.staticTexts["Welcome to WaiComputer"].exists)
    }

    @MainActor
    func testOnboardingShowsRestartRequiredForAccessibilityPermissionRefresh() throws {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "onboarding_flow",
            forceOnboarding: true,
            permissionMock: "needs_restart_accessibility",
            launchArguments: ["-waiUserLanguage", "en", "-nativeOnboardingV4CurrentPage", "2"]
        )
        app.launch()
        app.activate()

        XCTAssertTrue(waitForElement(app.descendants(matching: .any).matching(identifier: "onboarding-permission-accessibility-restart-required").firstMatch, in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "onboarding-permission-accessibility-restart").firstMatch, in: app, timeout: 3))
        XCTAssertFalse(app.buttons.matching(identifier: "onboarding-permission-accessibility-grant").firstMatch.exists)
        XCTAssertFalse(app.buttons.matching(identifier: "onboarding-permission-microphone-grant").firstMatch.exists)

        let primaryButton = app.buttons.matching(identifier: "onboarding-get-started-button").firstMatch
        XCTAssertTrue(waitForElement(primaryButton, in: app, timeout: 3))
        XCTAssertEqual(primaryButton.label, "Restart WaiComputer")
    }

    @MainActor
    func testOnboardingBackButtonReturnsToPreviousSlide() throws {
        let app = launchOnboarding(currentPage: 1, permissionMock: "missing")

        XCTAssertTrue(waitForElement(app.staticTexts["Two ways to use WaiComputer"], in: app, timeout: 8))

        app.buttons.matching(identifier: "onboarding-back-button").firstMatch.click()

        XCTAssertTrue(waitForElement(app.staticTexts["Welcome to WaiComputer"], in: app, timeout: 3))
    }

    @MainActor
    func testOnboardingWelcomeCanSwitchToRussianImmediately() throws {
        let app = launchOnboarding(
            currentPage: 0,
            permissionMock: "missing",
            launchArguments: ["-waiUserLanguage", "en"]
        )

        XCTAssertTrue(waitForElement(app.staticTexts["Welcome to WaiComputer"], in: app, timeout: 8))

        let russianButton = app.buttons.matching(identifier: "onboarding-language-russian").firstMatch
        XCTAssertTrue(waitForElement(russianButton, in: app, timeout: 3))
        russianButton.click()

        XCTAssertTrue(waitForElement(app.staticTexts["Добро пожаловать в WaiComputer"], in: app, timeout: 3))
    }

    @MainActor
    func testRussianPermissionSlideDoesNotMixEnglishMicrophoneCopy() throws {
        let app = launchOnboarding(
            currentPage: 2,
            permissionMock: "missing",
            launchArguments: ["-waiUserLanguage", "ru"]
        )

        XCTAssertTrue(waitForElement(app.staticTexts["Разрешения для WaiComputer"], in: app, timeout: 8))
        XCTAssertTrue(waitForElement(app.staticTexts["Микрофон нужен для диктовки, заметок и встреч"], in: app, timeout: 3))
        XCTAssertFalse(app.staticTexts["access the microphone."].exists)
    }

    @MainActor
    func testHotkeySelectionUpdatesWithoutLeavingHotkeySlide() throws {
        let app = launchOnboarding(currentPage: 4, permissionMock: "missing")

        XCTAssertTrue(waitForElement(app.staticTexts["Pick your dictation key"], in: app, timeout: 8))

        let leftOption = app.buttons.matching(identifier: "onboarding-hotkey-left_option").firstMatch
        XCTAssertTrue(waitForElement(leftOption, in: app, timeout: 3))
        leftOption.click()

        XCTAssertTrue(waitForElement(app.staticTexts["Pick your dictation key"], in: app, timeout: 2))
        XCTAssertEqual(leftOption.value as? String, "Selected")
    }

    @MainActor
    private func launchOnboarding(
        currentPage: Int,
        permissionMock: String,
        launchArguments extraLaunchArguments: [String] = []
    ) -> XCUIApplication {
        let app = XCUIApplication()
        let defaultLanguageArguments: [String]
        if extraLaunchArguments.contains("-waiUserLanguage") {
            defaultLanguageArguments = []
        } else {
            defaultLanguageArguments = ["-waiUserLanguage", "en"]
        }
        app.configureWaiComputerUITestLaunch(
            scenario: "onboarding_flow",
            forceOnboarding: true,
            permissionMock: permissionMock,
            launchArguments: defaultLanguageArguments + extraLaunchArguments + [
                "-nativeOnboardingV4CurrentPage", "\(currentPage)",
            ]
        )
        app.launch()
        app.activate()
        return app
    }

    private func waitForElement(_ element: XCUIElement, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let exists = element.waitForExistence(timeout: timeout)
        if !exists {
            XCTFail("Element not found. App hierarchy:\n\(app.debugDescription)")
        }
        return exists
    }
}
