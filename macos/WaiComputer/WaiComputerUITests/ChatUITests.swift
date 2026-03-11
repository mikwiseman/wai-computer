import XCTest

final class ChatUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func launchToChat() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["UITEST_SCENARIO"] = "main_view"
        app.launch()
        app.activate()

        // Wait for sidebar to load, then navigate to Chat
        let sidebar = app.descendants(matching: .any)
            .matching(identifier: "sidebar")
            .firstMatch
        _ = sidebar.waitForExistence(timeout: 8)

        let chatButton = app.buttons.matching(identifier: "sidebar-chat").firstMatch
        _ = chatButton.waitForExistence(timeout: 5)
        app.activate()
        chatButton.tap()

        return app
    }

    private func waitForElement(_ element: XCUIElement, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let exists = element.waitForExistence(timeout: timeout)
        if !exists {
            XCTFail("Element not found. App hierarchy:\n\(app.debugDescription)")
        }
        return exists
    }

    // MARK: - Chat

    @MainActor
    func testChatViewElements() throws {
        let app = launchToChat()

        // Chat input field (found by accessibility identifier)
        let chatInput = app.textFields.matching(identifier: "chat-input-field").firstMatch
        XCTAssertTrue(waitForElement(chatInput, in: app, timeout: 5))

        // New session button
        let newSessionButton = app.buttons.matching(identifier: "chat-new-session-button").firstMatch
        XCTAssertTrue(waitForElement(newSessionButton, in: app, timeout: 3))
    }

    @MainActor
    func testChatInputFieldAcceptsText() throws {
        let app = launchToChat()

        // Wait for chat input field
        let chatInput = app.textFields.matching(identifier: "chat-input-field").firstMatch
        XCTAssertTrue(waitForElement(chatInput, in: app, timeout: 5))

        // Click and type into the input field
        chatInput.tap()
        chatInput.typeText("Hello, test message")

        // Verify text was entered — the field value should contain the typed text
        let fieldValue = chatInput.value as? String ?? ""
        XCTAssertTrue(fieldValue.contains("Hello, test message"),
                       "Chat input should contain typed text, got: \(fieldValue)")
    }

    @MainActor
    func testNewSessionButton() throws {
        let app = launchToChat()

        // New session button should exist and be tappable
        let newSessionButton = app.buttons.matching(identifier: "chat-new-session-button").firstMatch
        XCTAssertTrue(waitForElement(newSessionButton, in: app, timeout: 5))
        XCTAssertTrue(newSessionButton.isEnabled, "New session button should be enabled")

        // Tap it — view should not crash, input field should still exist
        newSessionButton.tap()

        let chatInput = app.textFields.matching(identifier: "chat-input-field").firstMatch
        XCTAssertTrue(chatInput.waitForExistence(timeout: 3),
                       "Chat input should still exist after tapping new session")
    }
}
