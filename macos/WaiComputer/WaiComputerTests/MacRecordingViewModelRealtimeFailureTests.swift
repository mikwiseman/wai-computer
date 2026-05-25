import XCTest
import WaiComputerKit

@MainActor
final class MacRecordingViewModelRealtimeFailureTests: XCTestCase {
    func testReconnectionFailureKeepsLocalRecordingActive() async {
        let viewModel = MacRecordingViewModel(testingMode: .live)
        viewModel.testingBeginRecordingForRealtimeFailure(recordingId: "rec-local", duration: 124)

        await viewModel.testingHandleWebSocketEvent(
            .reconnectionFailed(WebSocketConnectionError.reconnectionExhausted(10))
        )

        XCTAssertEqual(viewModel.phase, .recording)
        XCTAssertTrue(viewModel.isRecording)
        XCTAssertTrue(viewModel.liveTranscriptionOffline)
        XCTAssertEqual(viewModel.connectionState, .connected)
        XCTAssertEqual(viewModel.currentRecordingId, "rec-local")
        XCTAssertNil(viewModel.error)
    }

    func testWebSocketDisconnectKeepsLocalRecordingActive() async {
        let viewModel = MacRecordingViewModel(testingMode: .live)
        viewModel.testingBeginRecordingForRealtimeFailure(recordingId: "rec-local", duration: 30)

        await viewModel.testingHandleWebSocketEvent(
            .disconnected(WebSocketConnectionError.disconnected(URLError(.networkConnectionLost)))
        )

        XCTAssertEqual(viewModel.phase, .recording)
        XCTAssertTrue(viewModel.isRecording)
        XCTAssertTrue(viewModel.liveTranscriptionOffline)
        XCTAssertEqual(viewModel.connectionState, .connected)
        XCTAssertEqual(viewModel.currentRecordingId, "rec-local")
        XCTAssertNil(viewModel.error)
    }
}
