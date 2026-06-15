import XCTest

final class PendingRecordingSyncCoordinatorSourceTests: XCTestCase {
    func testBackupListingFailuresAreNotTreatedAsEmptyPendingWork() throws {
        let source = try repoSource(
            "shared/WaiComputerKit/Sources/WaiComputerKit/Recording/PendingRecordingSyncCoordinator.swift"
        )

        XCTAssertFalse(source.contains("(try? RecordingBackupStore.listBackups().count) ?? 0"))
        XCTAssertFalse(source.contains("(try? RecordingBackupStore.listBackups()) ?? []"))
        XCTAssertTrue(source.contains("\"listPendingRecordingBackups\""))
        XCTAssertTrue(source.contains("\"listPendingRecordingBackupsForSync\""))
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
