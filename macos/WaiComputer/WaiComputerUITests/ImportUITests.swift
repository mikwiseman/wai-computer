import XCTest

final class ImportUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        try requireForegroundXCUITestOptIn()
    }

    private func launchAuthenticatedApp() -> XCUIApplication {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "main_view",
            skipOnboarding: true,
            launchArguments: ["-waiUserLanguage", "en"]
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

    // MARK: - Import

    @MainActor
    func testImportButtonExists() throws {
        let app = launchAuthenticatedApp()

        // Wait for sidebar to confirm main view has loaded
        let sidebar = app.descendants(matching: .any)
            .matching(identifier: "sidebar")
            .firstMatch
        XCTAssertTrue(waitForElement(sidebar, in: app, timeout: 8))

        // The default detail view shows the new recording view with an import button
        let importButton = app.descendants(matching: .any)
            .matching(identifier: "import-audio-button")
            .firstMatch
        XCTAssertTrue(waitForElement(importButton, in: app, timeout: 5))
    }

    @MainActor
    func testImportViewElements() throws {
        let app = launchAuthenticatedApp()

        // Wait for sidebar to confirm main view has loaded
        let sidebar = app.descendants(matching: .any)
            .matching(identifier: "sidebar")
            .firstMatch
        XCTAssertTrue(waitForElement(sidebar, in: app, timeout: 8))

        // Verify the import button exists with expected label content
        let importButton = app.descendants(matching: .any)
            .matching(identifier: "import-audio-button")
            .firstMatch
        XCTAssertTrue(waitForElement(importButton, in: app, timeout: 5))

        // Verify the button label contains expected text
        let label = importButton.label
        XCTAssertTrue(label.contains("Import Audio File"),
                       "Import button label should contain 'Import Audio File', got: \(label)")
        XCTAssertTrue(label.contains("Transcribe an existing audio file"),
                       "Import button label should contain subtitle text, got: \(label)")

        // Verify the recording options are also present (confirms full new recording view)
        let startRecordingButton = app.descendants(matching: .any)
            .matching(identifier: "start-recording-button")
            .firstMatch
        XCTAssertTrue(waitForElement(startRecordingButton, in: app, timeout: 3))
    }

    @MainActor
    func testRussianNewRecordingAndImportCopy() throws {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "main_view",
            skipOnboarding: true,
            launchArguments: ["-waiUserLanguage", "ru"]
        )
        app.launch()
        app.activate()

        let sidebar = app.descendants(matching: .any)
            .matching(identifier: "sidebar")
            .firstMatch
        XCTAssertTrue(waitForElement(sidebar, in: app, timeout: 8))

        XCTAssertTrue(waitForElement(app.staticTexts["Новая запись"], in: app, timeout: 5))
        let importButton = app.descendants(matching: .any)
            .matching(identifier: "import-audio-button")
            .firstMatch
        XCTAssertTrue(waitForElement(importButton, in: app, timeout: 3))

        let importLabel = importButton.label
        XCTAssertTrue(importLabel.contains("Импорт аудиофайла"),
                      "Import button label should contain Russian title, got: \(importLabel)")
        XCTAssertTrue(importLabel.contains("Расшифровать готовый аудиофайл"),
                      "Import button label should contain Russian subtitle, got: \(importLabel)")
    }
}
