import XCTest

final class SearchUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        try requireForegroundXCUITestOptIn()
    }

    private func launchToSearch() -> XCUIApplication {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "main_view",
            skipOnboarding: true
        )
        app.launch()
        app.activate()

        // Wait for sidebar to load, then navigate to Search
        let sidebar = app.descendants(matching: .any)
            .matching(identifier: "sidebar")
            .firstMatch
        _ = sidebar.waitForExistence(timeout: 8)

        let searchButton = app.buttons.matching(identifier: "sidebar-search").firstMatch
        _ = searchButton.waitForExistence(timeout: 5)
        app.activate()
        searchButton.tap()

        return app
    }

    private func waitForElement(_ element: XCUIElement, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let exists = element.waitForExistence(timeout: timeout)
        if !exists {
            XCTFail("Element not found. App hierarchy:\n\(app.debugDescription)")
        }
        return exists
    }

    // MARK: - Search

    @MainActor
    func testSearchViewElements() throws {
        let app = launchToSearch()

        // Search text field (found by placeholder)
        let searchField = app.textFields["Search recordings..."]
        XCTAssertTrue(waitForElement(searchField, in: app, timeout: 5))

        let searchButton = app.buttons.matching(identifier: "search-submit-button").firstMatch
        XCTAssertTrue(waitForElement(searchButton, in: app, timeout: 3))
        XCTAssertEqual(searchButton.label, "Search")

        // Empty state text
        let emptyStateText = app.staticTexts.matching(identifier: "search-empty-state").firstMatch
        XCTAssertTrue(waitForElement(emptyStateText, in: app, timeout: 3))
    }

    @MainActor
    func testSearchViewKeepsUniversalSearchField() throws {
        let app = launchToSearch()

        // Verify search field appears (confirms we're on the search screen)
        let searchField = app.textFields["Search recordings..."]
        XCTAssertTrue(waitForElement(searchField, in: app, timeout: 5))

        XCTAssertFalse(app.buttons.matching(identifier: "tab-hybrid").firstMatch.exists)
        XCTAssertFalse(app.buttons.matching(identifier: "tab-semantic").firstMatch.exists)
        XCTAssertFalse(app.buttons.matching(identifier: "tab-full-text").firstMatch.exists)
        XCTAssertTrue(searchField.exists, "Search field should remain after switching modes")
    }

    @MainActor
    func testSearchResultRowOpensRecording() throws {
        let app = launchToSearch()

        let searchField = app.textFields["Search recordings..."]
        XCTAssertTrue(waitForElement(searchField, in: app, timeout: 5))
        searchField.click()
        searchField.typeText("search")

        let searchButton = app.buttons.matching(identifier: "search-submit-button").firstMatch
        XCTAssertTrue(waitForElement(searchButton, in: app, timeout: 3))
        searchButton.tap()

        let resultRow = app.buttons.matching(identifier: "search-result-row-rec-1").firstMatch
        XCTAssertTrue(waitForElement(resultRow, in: app, timeout: 3))
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label MATCHES %@", #"^\d+%$"#)).firstMatch.exists)

        resultRow.tap()

        let transcriptText = app.staticTexts["Good morning everyone. Let us go through our updates for this week."]
        XCTAssertTrue(waitForElement(transcriptText, in: app, timeout: 5))
    }
}
