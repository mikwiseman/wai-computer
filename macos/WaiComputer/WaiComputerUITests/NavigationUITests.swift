import XCTest

final class NavigationUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        try requireForegroundXCUITestOptIn()
    }

    private func launchAuthenticatedApp() -> XCUIApplication {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "main_view",
            skipOnboarding: true
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

    // MARK: - Sidebar Navigation

    @MainActor
    func testSidebarNavigationExists() throws {
        let app = launchAuthenticatedApp()

        let sidebar = app.descendants(matching: .any)
            .matching(identifier: "sidebar")
            .firstMatch
        XCTAssertTrue(waitForElement(sidebar, in: app, timeout: 8))

        // Verify sidebar section items
        let inbox = app.descendants(matching: .any)
            .matching(identifier: "sidebar-inbox")
            .firstMatch
        XCTAssertTrue(waitForElement(inbox, in: app, timeout: 3))

        let trash = app.descendants(matching: .any)
            .matching(identifier: "sidebar-trash")
            .firstMatch
        XCTAssertTrue(waitForElement(trash, in: app, timeout: 3))

        let history = app.descendants(matching: .any)
            .matching(identifier: "sidebar-history")
            .firstMatch
        XCTAssertTrue(waitForElement(history, in: app, timeout: 3))

        let dictionary = app.descendants(matching: .any)
            .matching(identifier: "sidebar-dictionary")
            .firstMatch
        XCTAssertTrue(waitForElement(dictionary, in: app, timeout: 3))

        let search = app.descendants(matching: .any)
            .matching(identifier: "sidebar-search")
            .firstMatch
        XCTAssertTrue(waitForElement(search, in: app, timeout: 3))

        let wai = app.descendants(matching: .any)
            .matching(identifier: "sidebar-wai")
            .firstMatch
        XCTAssertTrue(waitForElement(wai, in: app, timeout: 3))

        let settings = app.descendants(matching: .any)
            .matching(identifier: "sidebar-settings")
            .firstMatch
        XCTAssertTrue(waitForElement(settings, in: app, timeout: 3))

        XCTAssertFalse(app.descendants(matching: .any).matching(identifier: "sidebar-agents").firstMatch.exists)
        XCTAssertFalse(app.descendants(matching: .any).matching(identifier: "sidebar-meetings").firstMatch.exists)
        XCTAssertFalse(app.descendants(matching: .any).matching(identifier: "sidebar-notes").firstMatch.exists)
        XCTAssertFalse(app.descendants(matching: .any).matching(identifier: "sidebar-reflections").firstMatch.exists)
    }

    @MainActor
    func testNavigateBetweenSections() throws {
        let app = launchAuthenticatedApp()

        // Wait for initial state — Inbox should be visible.
        let listTitle = app.descendants(matching: .any)
            .matching(identifier: "library-list-title")
            .firstMatch
        XCTAssertTrue(waitForElement(listTitle, in: app, timeout: 8))

        // Navigate to Search — search bar text field should appear
        let searchButton = app.buttons.matching(identifier: "sidebar-search").firstMatch
        XCTAssertTrue(waitForElement(searchButton, in: app, timeout: 3))
        app.activate()
        searchButton.tap()

        let searchField = app.textFields["Search your second brain..."]
        XCTAssertTrue(searchField.waitForExistence(timeout: 5), "Search text field should appear after navigating to Search")

        // Navigate to Wai — search field should leave, proving Wai is separate.
        let waiButton = app.buttons.matching(identifier: "sidebar-wai").firstMatch
        XCTAssertTrue(waitForElement(waiButton, in: app, timeout: 3))
        app.activate()
        waiButton.tap()
        XCTAssertFalse(searchField.waitForExistence(timeout: 2), "Search text field should not remain on Wai")

        // Navigate back to Inbox — list title should reappear.
        let inboxButton = app.buttons.matching(identifier: "sidebar-inbox").firstMatch
        XCTAssertTrue(waitForElement(inboxButton, in: app, timeout: 3))
        app.activate()
        inboxButton.tap()

        XCTAssertTrue(listTitle.waitForExistence(timeout: 5), "Library list title should reappear after navigating back")
    }
}
