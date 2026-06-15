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
