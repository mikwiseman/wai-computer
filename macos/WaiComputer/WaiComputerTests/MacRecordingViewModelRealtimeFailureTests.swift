import XCTest
import WaiComputerKit

@MainActor
final class MacRecordingViewModelStateTests: XCTestCase {
    func testPauseAndResumeKeepRecordingSessionActive() async {
        let viewModel = MacRecordingViewModel(testingMode: .uiTest(.recordingFlow))
        await viewModel.startRecording(
            apiClient: APIClient(baseURL: URL(string: "https://example.test")!),
            type: .meeting
        )

        await viewModel.pauseRecording()

        XCTAssertEqual(viewModel.phase, .recording)
        XCTAssertTrue(viewModel.isRecording)
        XCTAssertTrue(viewModel.isPaused)
        XCTAssertTrue(viewModel.canResumeRecording)
        XCTAssertTrue(viewModel.canStopRecording)
        XCTAssertEqual(viewModel.statusText(language: .english), "Paused")
        XCTAssertEqual(viewModel.statusText(language: .russian), "Пауза")
        XCTAssertEqual(viewModel.currentRecordingId, MacUITestFixtures.completedRecording.id)
        XCTAssertEqual(viewModel.duration, TimeInterval(MacUITestFixtures.completedRecording.durationSeconds ?? 0))

        await viewModel.resumeRecording()

        XCTAssertEqual(viewModel.phase, .recording)
        XCTAssertTrue(viewModel.isRecording)
        XCTAssertFalse(viewModel.isPaused)
        XCTAssertTrue(viewModel.canPauseRecording)
        XCTAssertEqual(viewModel.statusText(language: .english), "Recording")
        XCTAssertEqual(viewModel.currentRecordingId, MacUITestFixtures.completedRecording.id)
        XCTAssertEqual(viewModel.duration, TimeInterval(MacUITestFixtures.completedRecording.durationSeconds ?? 0))
    }

    func testMacRecordingViewModelDoesNotExposeRealtimeTranscriptionTestHooks() throws {
        let source = try macSource("WaiComputer/Features/Recording/MacRecordingViewModel.swift")

        XCTAssertFalse(source.contains("testingHandleWebSocketEvent"))
        XCTAssertFalse(source.contains("testingBeginRecordingForRealtimeFailure"))
        XCTAssertFalse(source.contains("WebSocketEvent"))
        XCTAssertFalse(source.contains("liveTranscriptionOffline"))
        XCTAssertFalse(source.contains("connectionState"))
    }

    private func macSource(_ relativePath: String) throws -> String {
        let file = try repoRoot().appendingPathComponent("macos/WaiComputer").appendingPathComponent(relativePath)
        return try String(contentsOf: file, encoding: .utf8)
    }

    private func repoRoot() throws -> URL {
        let candidates = [
            URL(fileURLWithPath: #filePath),
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath),
        ]

        for candidate in candidates {
            var directory = candidate.hasDirectoryPath ? candidate : candidate.deletingLastPathComponent()
            while directory.path != directory.deletingLastPathComponent().path {
                let marker = directory.appendingPathComponent("scripts/macos-peekaboo-smoke.sh")
                if FileManager.default.fileExists(atPath: marker.path) {
                    return directory
                }
                directory.deleteLastPathComponent()
            }
        }

        throw XCTSkip("Unable to locate wai-computer repo root from test runtime")
    }
}
