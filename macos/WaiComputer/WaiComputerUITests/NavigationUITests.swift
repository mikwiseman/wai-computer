import XCTest

final class NavigationUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func launchAuthenticatedApp() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["UITEST_SCENARIO"] = "main_view"
        app.launchEnvironment["WAI_SKIP_ONBOARDING"] = "1"
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

    // MARK: - Sidebar Navigation

    @MainActor
    func testSidebarNavigationExists() throws {
        let app = launchAuthenticatedApp()

        let sidebar = app.descendants(matching: .any)
            .matching(identifier: "sidebar")
            .firstMatch
        XCTAssertTrue(waitForElement(sidebar, in: app, timeout: 8))

        // Verify Library section items
        let allRecordings = app.descendants(matching: .any)
            .matching(identifier: "sidebar-all-recordings")
            .firstMatch
        XCTAssertTrue(waitForElement(allRecordings, in: app, timeout: 3))

        let meetings = app.descendants(matching: .any)
            .matching(identifier: "sidebar-meetings")
            .firstMatch
        XCTAssertTrue(waitForElement(meetings, in: app, timeout: 3))

        let notes = app.descendants(matching: .any)
            .matching(identifier: "sidebar-notes")
            .firstMatch
        XCTAssertTrue(waitForElement(notes, in: app, timeout: 3))

        let trash = app.descendants(matching: .any)
            .matching(identifier: "sidebar-trash")
            .firstMatch
        XCTAssertTrue(waitForElement(trash, in: app, timeout: 3))

        let search = app.descendants(matching: .any)
            .matching(identifier: "sidebar-search")
            .firstMatch
        XCTAssertTrue(waitForElement(search, in: app, timeout: 3))

        let settings = app.descendants(matching: .any)
            .matching(identifier: "sidebar-settings")
            .firstMatch
        XCTAssertTrue(waitForElement(settings, in: app, timeout: 3))
    }

    @MainActor
    func testNavigateBetweenSections() throws {
        let app = launchAuthenticatedApp()

        // Wait for initial state — library list title should show "All Recordings"
        let listTitle = app.descendants(matching: .any)
            .matching(identifier: "library-list-title")
            .firstMatch
        XCTAssertTrue(waitForElement(listTitle, in: app, timeout: 8))

        // Navigate to Search — search bar text field should appear
        let searchButton = app.buttons.matching(identifier: "sidebar-search").firstMatch
        XCTAssertTrue(waitForElement(searchButton, in: app, timeout: 3))
        app.activate()
        searchButton.tap()

        let searchField = app.textFields["Search recordings..."]
        XCTAssertTrue(searchField.waitForExistence(timeout: 5), "Search text field should appear after navigating to Search")

        // Navigate back to All Recordings — list title should reappear
        let allRecordingsButton = app.buttons.matching(identifier: "sidebar-all-recordings").firstMatch
        XCTAssertTrue(waitForElement(allRecordingsButton, in: app, timeout: 3))
        app.activate()
        allRecordingsButton.tap()

        XCTAssertTrue(listTitle.waitForExistence(timeout: 5), "Library list title should reappear after navigating back")
    }
}
