import XCTest

final class SettingsUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        try requireForegroundXCUITestOptIn()
    }

    private func launchToSettings(permissionMock: String? = nil) -> XCUIApplication {
        let app = XCUIApplication()
        app.terminate()
        app.configureWaiComputerUITestLaunch(
            scenario: "main_view",
            skipOnboarding: true,
            permissionMock: permissionMock
        )
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

    private func revealElementIfNeeded(_ element: XCUIElement, in app: XCUIApplication) {
        guard !element.exists else { return }
        let settingsScrollView = app.scrollViews.allElementsBoundByIndex.first { $0.frame.width > 500 }
        let scrollContainer = settingsScrollView
            ?? (app.scrollViews.firstMatch.exists ? app.scrollViews.firstMatch : app.tables.firstMatch)
        guard scrollContainer.exists else { return }
        for _ in 0..<6 where !element.exists {
            scrollContainer.swipeUp()
        }
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

        let behaviorHeader = app.descendants(matching: .any)
            .matching(identifier: "settings-app-behavior-header")
            .firstMatch
        XCTAssertTrue(waitForElement(behaviorHeader, in: app, timeout: 3))

        let dockIconToggle = app.descendants(matching: .any)
            .matching(identifier: "settings-show-dock-icon-when-closed-toggle")
            .firstMatch
        XCTAssertTrue(waitForElement(dockIconToggle, in: app, timeout: 3))

        let serverDataHeader = app.descendants(matching: .any)
            .matching(identifier: "settings-server-data-header")
            .firstMatch
        revealElementIfNeeded(serverDataHeader, in: app)
        XCTAssertTrue(waitForElement(serverDataHeader, in: app, timeout: 3))

        let vpsIPField = app.textFields
            .matching(identifier: "settings-server-data-vps-ip-field")
            .firstMatch
        XCTAssertTrue(waitForElement(vpsIPField, in: app, timeout: 3))

        let setupButton = app.buttons
            .matching(identifier: "settings-server-data-check-button")
            .firstMatch
        XCTAssertTrue(waitForElement(setupButton, in: app, timeout: 3))
        XCTAssertFalse(
            app.buttons.matching(identifier: "settings-server-data-move-button").firstMatch.exists,
            "Mac self-host setup must stay native instead of opening the web dashboard."
        )

        // Sign out button
        let signOutButton = app.buttons.matching(identifier: "settings-sign-out-button").firstMatch
        XCTAssertTrue(waitForElement(signOutButton, in: app, timeout: 3))
    }

    @MainActor
    func testBetaToggleIsGroupedWithUpdateControls() throws {
        let app = launchToSettings()

        let checkForUpdatesButton = app.buttons
            .matching(identifier: "settings-check-for-updates-button")
            .firstMatch
        revealElementIfNeeded(checkForUpdatesButton, in: app)
        XCTAssertTrue(waitForElement(checkForUpdatesButton, in: app, timeout: 5))

        let betaUpdatesToggle = app.descendants(matching: .any)
            .matching(identifier: "settings-receive-beta-updates-toggle")
            .firstMatch
        XCTAssertTrue(waitForElement(betaUpdatesToggle, in: app, timeout: 3))

        XCTAssertTrue(
            betaUpdatesToggle.frame.midY < checkForUpdatesButton.frame.midY,
            "Receive beta updates should appear above Check for Updates."
        )
        XCTAssertLessThan(
            abs(checkForUpdatesButton.frame.midY - betaUpdatesToggle.frame.midY),
            180,
            "Receive beta updates should be grouped with the version and update controls."
        )
    }

    @MainActor
    func testSignOutButtonExists() throws {
        let app = launchToSettings()

        // Sign out button should exist and be hittable
        let signOutButton = app.buttons.matching(identifier: "settings-sign-out-button").firstMatch
        XCTAssertTrue(waitForElement(signOutButton, in: app, timeout: 5))
        XCTAssertTrue(signOutButton.isEnabled, "Sign Out button should be enabled")
    }

    @MainActor
    func testSignOutClearsLocalStateAndReturnsToAuth() throws {
        let app = launchToSettings()

        let signOutButton = app.buttons.matching(identifier: "settings-sign-out-button").firstMatch
        XCTAssertTrue(waitForElement(signOutButton, in: app, timeout: 5))
        signOutButton.tap()

        let confirmButton = app.buttons.matching(identifier: "settings-sign-out-confirm-button").firstMatch
        XCTAssertTrue(waitForElement(confirmButton, in: app, timeout: 3))
        confirmButton.tap()

        XCTAssertTrue(waitForElement(app.staticTexts["Welcome to WaiComputer"], in: app, timeout: 8))
    }

    @MainActor
    func testSettingsShowsRestartRequiredForAutomaticPastePermissionRefresh() throws {
        let app = launchToSettings(permissionMock: "needs_restart_paste")

        let restartRequired = app.descendants(matching: .any)
            .matching(identifier: "settings-permission-accessibility-restart-required")
            .firstMatch
        revealElementIfNeeded(restartRequired, in: app)

        XCTAssertTrue(waitForElement(restartRequired, in: app, timeout: 5))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "settings-permission-accessibility-settings").firstMatch, in: app, timeout: 3))
        XCTAssertTrue(waitForElement(app.buttons.matching(identifier: "settings-permission-accessibility-restart").firstMatch, in: app, timeout: 3))
        XCTAssertFalse(app.buttons.matching(identifier: "settings-permission-accessibility-grant").firstMatch.exists)
    }

    @MainActor
    func testSettingsShowsSystemAudioPermissionForMeetingRecordings() throws {
        let app = launchToSettings(permissionMock: "missing")

        let systemAudioButton = app.buttons
            .matching(identifier: "settings-permission-system-audio-grant")
            .firstMatch
        revealElementIfNeeded(systemAudioButton, in: app)

        XCTAssertTrue(waitForElement(systemAudioButton, in: app, timeout: 5))
        XCTAssertEqual(systemAudioButton.label, "Test System Audio")
        XCTAssertTrue(app.staticTexts["System Audio"].exists)
    }
}
