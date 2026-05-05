import XCTest

final class LibraryUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func waitForElement(_ element: XCUIElement, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let exists = element.waitForExistence(timeout: timeout)
        if !exists {
            XCTFail("Element not found. App hierarchy:\n\(app.debugDescription)")
        }
        return exists
    }

    // MARK: - Library

    @MainActor
    func testLibraryViewElements() throws {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["UITEST_SCENARIO"] = "main_view"
        app.launchEnvironment["WAI_SKIP_ONBOARDING"] = "1"
        app.launch()
        app.activate()

        // Wait for sidebar to confirm the main view has loaded
        let sidebar = app.descendants(matching: .any)
            .matching(identifier: "sidebar")
            .firstMatch
        XCTAssertTrue(waitForElement(sidebar, in: app, timeout: 8))

        // The default section is "All Recordings" — verify library list title appears
        let listTitle = app.descendants(matching: .any)
            .matching(identifier: "library-list-title")
            .firstMatch
        XCTAssertTrue(waitForElement(listTitle, in: app, timeout: 5))

        // Verify "All Recordings" is the displayed title
        XCTAssertEqual(listTitle.value as? String, "All Recordings")

        // Verify the start recording button exists in the detail column
        let startRecordingButton = app.buttons.matching(identifier: "start-recording-button").firstMatch
        XCTAssertTrue(waitForElement(startRecordingButton, in: app, timeout: 5))

        // Verify the new recording toolbar button exists
        let newRecordingToolbarButton = app.buttons.matching(identifier: "new-recording-toolbar-button").firstMatch
        XCTAssertTrue(waitForElement(newRecordingToolbarButton, in: app, timeout: 3))
    }
}
