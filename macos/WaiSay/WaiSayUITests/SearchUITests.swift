import XCTest

final class SearchUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func launchToSearch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["UITEST_SCENARIO"] = "main_view"
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

        // Mode tabs — Hybrid, Semantic, Full Text (found by identifier)
        let hybridTab = app.buttons.matching(identifier: "tab-hybrid").firstMatch
        XCTAssertTrue(waitForElement(hybridTab, in: app, timeout: 3))

        let semanticTab = app.buttons.matching(identifier: "tab-semantic").firstMatch
        XCTAssertTrue(waitForElement(semanticTab, in: app, timeout: 3))

        let ftsTab = app.buttons.matching(identifier: "tab-full-text").firstMatch
        XCTAssertTrue(waitForElement(ftsTab, in: app, timeout: 3))

        // Empty state text
        let emptyStateText = app.staticTexts.matching(identifier: "search-empty-state").firstMatch
        XCTAssertTrue(waitForElement(emptyStateText, in: app, timeout: 3))
    }

    @MainActor
    func testSearchModeSwitch() throws {
        let app = launchToSearch()

        // Verify search field appears (confirms we're on the search screen)
        let searchField = app.textFields["Search recordings..."]
        XCTAssertTrue(waitForElement(searchField, in: app, timeout: 5))

        // Verify Hybrid tab exists (default selected)
        let hybridTab = app.buttons.matching(identifier: "tab-hybrid").firstMatch
        XCTAssertTrue(waitForElement(hybridTab, in: app, timeout: 3))

        // Switch to Semantic
        let semanticTab = app.buttons.matching(identifier: "tab-semantic").firstMatch
        XCTAssertTrue(waitForElement(semanticTab, in: app, timeout: 3))
        semanticTab.tap()

        // Verify the tab is still visible (view didn't crash)
        XCTAssertTrue(semanticTab.exists, "Semantic tab should still exist after tapping")

        // Switch to Full Text
        let ftsTab = app.buttons.matching(identifier: "tab-full-text").firstMatch
        XCTAssertTrue(waitForElement(ftsTab, in: app, timeout: 3))
        ftsTab.tap()

        // Verify the tab is still visible
        XCTAssertTrue(ftsTab.exists, "Full Text tab should still exist after tapping")

        // Switch back to Hybrid
        hybridTab.tap()
        XCTAssertTrue(hybridTab.exists, "Hybrid tab should still exist after tapping")

        // Verify search field is still intact (view didn't break)
        XCTAssertTrue(searchField.exists, "Search field should remain after switching modes")
    }
}
