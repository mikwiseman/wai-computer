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

    /// The clock is the boundary-only model that keeps 1 Hz ticking out of
    /// @Published state: elapsed derives from wall time between boundaries.
    func testDurationClockElapsedAcrossRunAndPauseStretches() {
        let start = Date(timeIntervalSince1970: 1_000_000)

        // Idle clock: nothing accumulates.
        XCTAssertEqual(RecordingDurationClock().elapsed(at: start), 0)

        // Running stretch accumulates wall time on top of the base.
        let running = RecordingDurationClock(baseSeconds: 60, runningSince: start)
        XCTAssertEqual(running.elapsed(at: start.addingTimeInterval(30)), 90)

        // Paused clock is frozen at its base regardless of elapsed wall time.
        let paused = RecordingDurationClock(baseSeconds: 90, runningSince: nil)
        XCTAssertEqual(paused.elapsed(at: start.addingTimeInterval(3_600)), 90)

        // Clock skew (date before runningSince) never yields negative time.
        XCTAssertEqual(running.elapsed(at: start.addingTimeInterval(-5)), 60)

        XCTAssertEqual(RecordingDurationClock.formatted(0), "00:00")
        XCTAssertEqual(RecordingDurationClock.formatted(90), "01:30")
        // Hours roll up — a 1h+ meeting must never read "60:01".
        XCTAssertEqual(RecordingDurationClock.formatted(3_601), "1:00:01")
        XCTAssertEqual(RecordingDurationClock.formatted(12_520), "3:28:40")
    }

    /// The recording timer must not tick `duration` once per second — that
    /// invalidated every observer of the view model (the whole window) for
    /// the length of a recording. Live timers render via TimelineView from
    /// `durationClock` instead; this pins the source so the tick can't creep
    /// back in.
    func testTimerLoopDoesNotTickPublishedDuration() throws {
        let source = try macSource("WaiComputer/Features/Recording/MacRecordingViewModel.swift")
        XCTAssertFalse(source.contains("duration += 1"))
        XCTAssertFalse(source.contains("self.duration += 1"))
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
