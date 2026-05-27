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
        app.configureWaiComputerUITestLaunch(
            scenario: "main_view",
            skipOnboarding: true
        )
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

    @MainActor
    func testProcessingRecordingShowsProcessingTranscriptState() throws {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "main_view",
            skipOnboarding: true
        )
        app.launch()
        app.activate()

        let processingRecording = app.staticTexts["Processing Recording"].firstMatch
        XCTAssertTrue(waitForElement(processingRecording, in: app, timeout: 8))
        processingRecording.tap()

        let processingState = app.descendants(matching: .any)
            .matching(identifier: "transcript-processing-state")
            .firstMatch
        XCTAssertTrue(waitForElement(processingState, in: app, timeout: 5))
        XCTAssertFalse(app.staticTexts["No Transcript"].exists)

        let listTitle = app.descendants(matching: .any)
            .matching(identifier: "library-list-title")
            .firstMatch
        XCTAssertTrue(waitForElement(listTitle, in: app, timeout: 3))

        let detailTitle = app.descendants(matching: .any)
            .matching(identifier: "recording-title")
            .firstMatch
        XCTAssertTrue(waitForElement(detailTitle, in: app, timeout: 3))
        XCTAssertLessThanOrEqual(
            detailTitle.frame.minY,
            listTitle.frame.minY + 80,
            "Recording detail title should stay top-aligned with the list header, not centered in the detail pane."
        )
    }

    @MainActor
    func testNewFolderSheetHasStableWidth() throws {
        let app = XCUIApplication()
        app.configureWaiComputerUITestLaunch(
            scenario: "main_view",
            skipOnboarding: true
        )
        app.launch()
        app.activate()

        let newFolderButton = app.buttons.matching(identifier: "sidebar-new-folder").firstMatch
        XCTAssertTrue(waitForElement(newFolderButton, in: app, timeout: 5))
        newFolderButton.tap()

        let folderSheet = app.descendants(matching: .any)
            .matching(identifier: "folder-name-sheet")
            .firstMatch
        XCTAssertTrue(waitForElement(folderSheet, in: app, timeout: 5))
        XCTAssertGreaterThanOrEqual(folderSheet.frame.width, 700)
        XCTAssertLessThanOrEqual(folderSheet.frame.width, 740)
    }
}
