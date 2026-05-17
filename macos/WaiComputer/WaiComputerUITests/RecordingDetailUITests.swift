import XCTest

final class RecordingDetailUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    /// Launch the app in the recording_flow scenario, start and stop a recording,
    /// then wait for the recording detail view to appear.
    private func launchToRecordingDetail() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["UITEST_SCENARIO"] = "recording_flow"
        app.launchEnvironment["WAI_SKIP_ONBOARDING"] = "1"
        app.launch()
        app.activate()

        // Start recording
        let startButton = app.buttons.matching(identifier: "start-recording-button").firstMatch
        _ = startButton.waitForExistence(timeout: 5)
        app.activate()
        XCTAssertTrue(startButton.isHittable)
        startButton.tap()

        // Wait for live recording view
        let liveView = app.descendants(matching: .any)
            .matching(identifier: "live-recording-view")
            .firstMatch
        _ = waitForElement(liveView, in: app, timeout: 5)

        // Stop recording
        let stopButton = app.buttons.matching(identifier: "stop-recording-button").firstMatch
        _ = waitForElement(stopButton, in: app, timeout: 5)
        app.activate()
        stopButton.tap()

        // Wait for the detail view to appear
        let detailRoot = app.descendants(matching: .any)
            .matching(identifier: "recording-detail-root")
            .firstMatch
        _ = waitForElement(detailRoot, in: app, timeout: 10)

        return app
    }

    private func waitForElement(_ element: XCUIElement, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let exists = element.waitForExistence(timeout: timeout)
        if !exists {
            XCTFail("Element not found. App hierarchy:\n\(app.debugDescription)")
        }
        return exists
    }

    // MARK: - Recording Detail

    @MainActor
    func testRecordingDetailShowsTitle() throws {
        let app = launchToRecordingDetail()

        let title = app.descendants(matching: .any)
            .matching(identifier: "recording-title")
            .firstMatch
        XCTAssertTrue(waitForElement(title, in: app, timeout: 5))
    }

    @MainActor
    func testRecordingDetailShowsTranscript() throws {
        let app = launchToRecordingDetail()

        // Transcript tab should be selected by default — verify transcript content
        let transcriptContent = app.descendants(matching: .any)
            .matching(identifier: "transcript-content")
            .firstMatch
        XCTAssertTrue(waitForElement(transcriptContent, in: app, timeout: 5))

        // Verify the fixture transcript text is visible
        let transcriptText = app.staticTexts["UI test finalized transcript."].firstMatch
        XCTAssertTrue(waitForElement(transcriptText, in: app, timeout: 3))
    }

    @MainActor
    func testRecordingDetailShowsSummary() throws {
        let app = launchToRecordingDetail()

        // Switch to Summary tab
        let summaryTab = app.buttons.matching(identifier: "tab-summary").firstMatch
        XCTAssertTrue(waitForElement(summaryTab, in: app, timeout: 3))
        app.activate()
        summaryTab.tap()

        // The fixture has no summary — verify empty state appears
        let summaryEmptyState = app.descendants(matching: .any)
            .matching(identifier: "summary-empty-state")
            .firstMatch
        XCTAssertTrue(waitForElement(summaryEmptyState, in: app, timeout: 5))
    }

    @MainActor
    func testRecordingDetailShowsActionItems() throws {
        let app = launchToRecordingDetail()

        // Switch to Action Items tab
        let actionsTab = app.buttons.matching(identifier: "tab-action-items").firstMatch
        XCTAssertTrue(waitForElement(actionsTab, in: app, timeout: 3))
        app.activate()
        actionsTab.tap()

        // The fixture has no action items or summary — verify empty state appears
        let actionsEmptyState = app.descendants(matching: .any)
            .matching(identifier: "actions-empty-state")
            .firstMatch
        XCTAssertTrue(waitForElement(actionsEmptyState, in: app, timeout: 5))
    }
}
