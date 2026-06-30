import XCTest

final class NativeRecordingFinalizationSourceTests: XCTestCase {
    func testNativeRecordingStopDoesNotSwallowAudioFinalizationFailures() throws {
        let macSource = try repoSource("macos/WaiComputer/WaiComputer/Features/Recording/MacRecordingViewModel.swift")
        let iosSource = try repoSource("ios/WaiComputer/WaiComputer/Features/Recording/RecordingViewModel.swift")

        for source in [macSource, iosSource] {
            let stopRecording = try functionBody(
                named: "func stopRecording() async",
                in: source,
                endingBefore: "/// Abort an in-progress recording without saving anything."
            )
            XCTAssertTrue(stopRecording.contains("finalizeRecordingAudioForPersistence("))
            XCTAssertFalse(stopRecording.contains("try? fileWriter?.finalize()"))
            XCTAssertFalse(stopRecording.contains("try? fileWriter.finalize()"))

            XCTAssertTrue(source.contains("recording.audio.finalize_failed"))
            XCTAssertTrue(source.contains("AudioFileWriter.repairWAVHeaderSizes(fileURL: fileWriter.fileURL)"))
            XCTAssertTrue(source.contains("recording.audio.finalize_repaired"))
            XCTAssertTrue(source.contains("recording.audio.repair_after_finalize_failed"))
        }
    }

    func testIOSRecordingRealtimeCloseFailuresAreCapturedDuringFinalization() throws {
        let macSource = try repoSource("macos/WaiComputer/WaiComputer/Features/Recording/MacRecordingViewModel.swift")
        let iosSource = try repoSource("ios/WaiComputer/WaiComputer/Features/Recording/RecordingViewModel.swift")

        let iosFinishStreaming = try functionBody(
            named: "private func finishStreaming(_ manager: WebSocketManager?) async -> Bool",
            in: iosSource,
            endingBefore: "private func startTimer()"
        )

        XCTAssertFalse(macSource.contains("private func finishStreaming(_ manager: WebSocketManager?) async -> Bool"))
        XCTAssertTrue(iosFinishStreaming.contains("recording.provider.close_failed"))
        XCTAssertTrue(iosFinishStreaming.contains("SentryHelper.captureError("))
        XCTAssertTrue(iosFinishStreaming.contains("SentryHelper.addBreadcrumb("))
        XCTAssertTrue(iosFinishStreaming.contains("\"stage\": \"recording_finalize\""))
        XCTAssertFalse(iosFinishStreaming.contains("catch {\n            recordingLog.warning(\"Failed to finalize realtime transcription stream\")\n            return false"))
    }

    func testMacRecordingStopPersistsCloudFirstBeforeFallingBackToBackgroundSync() throws {
        let macSource = try repoSource("macos/WaiComputer/WaiComputer/Features/Recording/MacRecordingViewModel.swift")

        let stopRecording = try functionBody(
            named: "func stopRecording() async",
            in: macSource,
            endingBefore: "/// Honest-failure path for the audio loop:"
        )

        XCTAssertTrue(
            stopRecording.contains("persistRecordingCloudFirst("),
            "Meeting stop should immediately push the finalized recording to server processing when the API is reachable."
        )
        XCTAssertFalse(
            stopRecording.contains("persistRecordingForBackgroundSync("),
            "Background sync should be the fallback path, not the primary stop path for finished meetings."
        )
    }

    func testMacRecordingDoesNotStartRealtimeTranscriptionDuringRecording() throws {
        let macSource = try repoSource("macos/WaiComputer/WaiComputer/Features/Recording/MacRecordingViewModel.swift")

        let startRecording = try functionBody(
            named: "func startRecording(",
            in: macSource,
            endingBefore: "    func stopRecording() async"
        )

        XCTAssertFalse(
            startRecording.contains("createRealtimeTranscriptionSession("),
            "Native meeting recording should not stream audio to realtime STT while capture is still in progress."
        )
        XCTAssertFalse(
            startRecording.contains("WebSocketManager("),
            "Native meeting recording should rely on final audio upload, not an in-progress transcript socket."
        )
        XCTAssertFalse(
            startRecording.contains("sendAudio(data:"),
            "Recording buffers should be written locally only; final transcription starts after Stop."
        )
    }

    func testMacRecordingStopDoesNotFinalizeRealtimeTranscriptSegments() throws {
        let macSource = try repoSource("macos/WaiComputer/WaiComputer/Features/Recording/MacRecordingViewModel.swift")

        let stopRecording = try functionBody(
            named: "func stopRecording() async",
            in: macSource,
            endingBefore: "/// Honest-failure path for the audio loop:"
        )

        XCTAssertFalse(
            stopRecording.contains("finishStreaming("),
            "Stop should finalize local audio and upload it for canonical file STT, not drain a live transcript."
        )
        XCTAssertFalse(
            stopRecording.contains("collectedSegments"),
            "Stop should not save in-progress realtime transcript segments as the final transcript."
        )
    }

    private func functionBody(
        named declaration: String,
        in source: String,
        endingBefore terminator: String
    ) throws -> String {
        guard let start = source.range(of: declaration)?.lowerBound,
              let end = source[start...].range(of: terminator)?.lowerBound else {
            throw XCTSkip("Unable to locate \(declaration)")
        }
        return String(source[start..<end])
    }

    private func repoSource(_ relativePath: String) throws -> String {
        try String(contentsOf: try repoRoot().appendingPathComponent(relativePath), encoding: .utf8)
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
