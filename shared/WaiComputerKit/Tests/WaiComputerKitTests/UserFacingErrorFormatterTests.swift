import XCTest
@testable import WaiComputerKit

final class UserFacingErrorFormatterTests: XCTestCase {
    func testLibraryHidesInternalServerError() {
        let error = APIError.httpError(statusCode: 500, message: "Internal Server Error")
        XCTAssertEqual(
            error.userFacingMessage(context: .library),
            "We couldn't load your library right now. Please try again in a moment."
        )
    }

    func testRecordingUsesFriendlyReconnectMessage() {
        let error = WebSocketConnectionError.reconnectionExhausted(10)
        XCTAssertEqual(
            error.userFacingMessage(context: .recording),
            "We couldn't keep the live recording connected. Check your internet connection and try again."
        )
    }

    func testAuthenticationUsesFriendlyNetworkMessage() {
        let error = APIError.networkError(URLError(.notConnectedToInternet))
        XCTAssertEqual(
            error.userFacingMessage(context: .authentication),
            "We couldn't reach Wai to sign you in. Check your internet connection and try again."
        )
    }

    func testDisplayMessageFallsBackForTechnicalServerMessage() {
        XCTAssertEqual(
            UserFacingErrorFormatter.displayMessage(
                "Internal Server Error",
                fallback: "Transcript was saved, but processing failed.",
                context: .recording
            ),
            "Transcript was saved, but processing failed."
        )
    }

    func testDisplayMessagePreservesReadableServerMessage() {
        XCTAssertEqual(
            UserFacingErrorFormatter.displayMessage(
                "We finished saving your recording, but summary generation needs another try.",
                fallback: "Transcript was saved, but processing failed.",
                context: .recording
            ),
            "We finished saving your recording, but summary generation needs another try."
        )
    }

    func testDisplayMessageFallsBackForReconnectMessageWithLocalPath() {
        let technicalMessage = """
        Connection lost after retrying. Your audio recording and 103 transcript segments were saved locally.
        /Users/test/Library/Application Support/WaiComputer/PendingTranscripts/example
        Failed to reconnect after 10 attempts.
        """

        XCTAssertEqual(
            UserFacingErrorFormatter.displayMessage(
                technicalMessage,
                fallback: "Your recording is safe on this device. We'll keep syncing it automatically in the background.",
                context: .recording
            ),
            "Your recording is safe on this device. We'll keep syncing it automatically in the background."
        )
    }
}
