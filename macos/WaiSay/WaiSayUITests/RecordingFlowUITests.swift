import XCTest

final class RecordingFlowUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testStopRecordingTransitionsIntoSavedRecordingDetail() throws {
        let app = XCUIApplication()
        app.launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        app.launchEnvironment["UITEST_SCENARIO"] = "recording_flow"
        app.launchEnvironment["WAI_SKIP_ONBOARDING"] = "1"
        app.launch()
        app.activate()

        let startButton = app.descendants(matching: .any)
            .matching(identifier: "start-recording-button")
            .firstMatch
        XCTAssertTrue(startButton.waitForExistence(timeout: 5))
        app.activate()
        startButton.tap()

        let liveRecordingView = app.descendants(matching: .any)
            .matching(identifier: "live-recording-view")
            .firstMatch
        XCTAssertTrue(waitForElement(liveRecordingView, in: app, timeout: 5))

        let stopButton = app.descendants(matching: .any)
            .matching(identifier: "stop-recording-button")
            .firstMatch
        XCTAssertTrue(waitForElement(stopButton, in: app, timeout: 5))
        XCTAssertTrue(stopButton.isHittable)
        app.activate()
        stopButton.tap()

        let detailRoot = app.descendants(matching: .any)
            .matching(identifier: "recording-detail-root")
            .firstMatch
        XCTAssertTrue(waitForElement(detailRoot, in: app, timeout: 5))

        let title = app.descendants(matching: .any)
            .matching(identifier: "recording-title")
            .firstMatch
        XCTAssertTrue(waitForElement(title, in: app, timeout: 5))
        let finalizedTranscript = detailRoot.staticTexts["UI test finalized transcript."]
        XCTAssertTrue(waitForElement(finalizedTranscript, in: app, timeout: 5))
    }

    private func waitForElement(_ element: XCUIElement, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let exists = element.waitForExistence(timeout: timeout)
        if !exists {
            XCTFail(app.debugDescription)
        }
        return exists
    }
}
