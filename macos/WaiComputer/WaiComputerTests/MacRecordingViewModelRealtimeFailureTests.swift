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

    func testPauseAndResumeKeepRecordingSessionActive() async {
        let viewModel = MacRecordingViewModel(testingMode: .live)
        viewModel.testingBeginRecordingForRealtimeFailure(recordingId: "rec-local", duration: 42)

        await viewModel.pauseRecording()

        XCTAssertEqual(viewModel.phase, .recording)
        XCTAssertTrue(viewModel.isRecording)
        XCTAssertTrue(viewModel.isPaused)
        XCTAssertTrue(viewModel.canResumeRecording)
        XCTAssertTrue(viewModel.canStopRecording)
        XCTAssertEqual(viewModel.statusText(language: .english), "Paused")
        XCTAssertEqual(viewModel.statusText(language: .russian), "Пауза")
        XCTAssertEqual(viewModel.currentRecordingId, "rec-local")
        XCTAssertEqual(viewModel.duration, 42)

        await viewModel.resumeRecording()

        XCTAssertEqual(viewModel.phase, .recording)
        XCTAssertTrue(viewModel.isRecording)
        XCTAssertFalse(viewModel.isPaused)
        XCTAssertTrue(viewModel.canPauseRecording)
        XCTAssertEqual(viewModel.statusText(language: .english), "Recording")
        XCTAssertEqual(viewModel.currentRecordingId, "rec-local")
        XCTAssertEqual(viewModel.duration, 42)
    }
}
