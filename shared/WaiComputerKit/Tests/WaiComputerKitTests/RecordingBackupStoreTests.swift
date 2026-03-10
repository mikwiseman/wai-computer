import Foundation
import XCTest
@testable import WaiComputerKit

final class RecordingBackupStoreTests: XCTestCase {
    func testSaveRecordingCreatesDurableFiles() throws {
        let recordingId = "backup-test-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        let backup = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Important note",
            recordingType: .note,
            durationSeconds: 42,
            transcript: "Hello",
            segments: [
                LiveTranscriptSegment(
                    text: "Hello",
                    speaker: "Speaker 1",
                    isFinal: true,
                    startMs: 0,
                    endMs: 500,
                    confidence: 0.98
                )
            ]
        )

        XCTAssertTrue(FileManager.default.fileExists(atPath: backup.manifestURL.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: backup.segmentsFileURL.path))

        let manifestData = try Data(contentsOf: backup.manifestURL)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(RecordingBackupManifest.self, from: manifestData)
        XCTAssertEqual(manifest.title, "Important note")
        XCTAssertEqual(manifest.transcript, "Hello")
    }

    func testRecordSaveFailureUpdatesManifest() throws {
        let recordingId = "backup-failure-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Meeting",
            recordingType: .meeting,
            durationSeconds: 12,
            transcript: nil,
            segments: []
        )

        let backup = try RecordingBackupStore.recordSaveFailure(
            recordingId: recordingId,
            message: "Save failed"
        )
        XCTAssertNotNil(backup)

        let manifestData = try Data(contentsOf: backup!.manifestURL)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(RecordingBackupManifest.self, from: manifestData)
        XCTAssertEqual(manifest.lastErrorMessage, "Save failed")
    }
}
