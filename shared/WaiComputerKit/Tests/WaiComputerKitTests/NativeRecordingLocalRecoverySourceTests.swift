import XCTest

final class NativeRecordingLocalRecoverySourceTests: XCTestCase {
    func testLocalRecoveryBackupFailuresAreNotSilentlyIgnored() throws {
        let macSource = try repoSource("macos/WaiComputer/WaiComputer/Features/Recording/MacRecordingViewModel.swift")
        let iosSource = try repoSource("ios/WaiComputer/WaiComputer/Features/Recording/RecordingViewModel.swift")

        let macRetryHelper = try functionBody(
            named: "private func saveLocalBackupForRetry(",
            in: macSource,
            endingBefore: "private func applyRecordingPersistenceResult"
        )
        XCTAssertFalse(macRetryHelper.contains("try? saveTranscriptBackup("))
        XCTAssertFalse(macRetryHelper.contains("try? RecordingBackupStore.recordSaveFailure("))
        XCTAssertTrue(macRetryHelper.contains("\"saveLocalBackupForRetry\""))
        XCTAssertTrue(macRetryHelper.contains("\"recordLocalRecoveryReason\""))

        let iosStopPersistence = try sourceRange(
            in: iosSource,
            startingAt: "// Persist the finalized live transcript.",
            endingBefore: "self.isServerComplete = transcriptSaved"
        )
        XCTAssertFalse(iosStopPersistence.contains("try? self.saveTranscriptBackup("))
        XCTAssertFalse(iosStopPersistence.contains("try? RecordingBackupStore.recordSaveFailure("))
        XCTAssertTrue(iosStopPersistence.contains("saveLocalBackupForRetry("))
    }

    private func functionBody(
        named declaration: String,
        in source: String,
        endingBefore terminator: String
    ) throws -> String {
        try sourceRange(in: source, startingAt: declaration, endingBefore: terminator)
    }

    private func sourceRange(
        in source: String,
        startingAt startMarker: String,
        endingBefore endMarker: String
    ) throws -> String {
        guard let start = source.range(of: startMarker)?.lowerBound,
              let end = source[start...].range(of: endMarker)?.lowerBound else {
            throw XCTSkip("Unable to locate source range")
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
