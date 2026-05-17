import Foundation
import XCTest
@testable import WaiComputerKit

final class RecordingBackupStoreTests: XCTestCase {
    private var backupRoot: URL!

    override func setUpWithError() throws {
        try super.setUpWithError()
        backupRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("WaiComputerKitTests")
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: backupRoot, withIntermediateDirectories: true)
        RecordingBackupStore.overrideBaseDirectory = backupRoot
    }

    override func tearDownWithError() throws {
        RecordingBackupStore.overrideBaseDirectory = nil
        if let backupRoot {
            try? FileManager.default.removeItem(at: backupRoot)
        }
        try super.tearDownWithError()
    }

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

    func testSaveRecordingWithEmptyTranscript() throws {
        let recordingId = "backup-empty-transcript-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        let backup = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Empty transcript note",
            recordingType: .note,
            durationSeconds: 5,
            transcript: nil,
            segments: []
        )

        XCTAssertTrue(FileManager.default.fileExists(atPath: backup.manifestURL.path))
        // segments file should NOT exist when segments array is empty
        XCTAssertFalse(FileManager.default.fileExists(atPath: backup.segmentsFileURL.path))

        let manifestData = try Data(contentsOf: backup.manifestURL)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(RecordingBackupManifest.self, from: manifestData)
        XCTAssertEqual(manifest.title, "Empty transcript note")
        XCTAssertNil(manifest.transcript)
        XCTAssertEqual(manifest.segmentCount, 0)
    }

    func testSaveRecordingWithMultipleSegments() throws {
        let recordingId = "backup-multi-seg-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        let segments = [
            LiveTranscriptSegment(
                text: "Good morning everyone.",
                speaker: "Speaker 1",
                isFinal: true,
                startMs: 0,
                endMs: 1500,
                confidence: 0.95
            ),
            LiveTranscriptSegment(
                text: "Thanks for joining.",
                speaker: "Speaker 2",
                isFinal: true,
                startMs: 1600,
                endMs: 3000,
                confidence: 0.91
            ),
            LiveTranscriptSegment(
                text: "Let's get started.",
                speaker: "Speaker 1",
                isFinal: true,
                startMs: 3100,
                endMs: 4200,
                confidence: 0.88
            ),
        ]

        let backup = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Team standup",
            recordingType: .meeting,
            durationSeconds: 4.2,
            transcript: "Good morning everyone. Thanks for joining. Let's get started.",
            segments: segments
        )

        XCTAssertTrue(FileManager.default.fileExists(atPath: backup.manifestURL.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: backup.segmentsFileURL.path))

        // Verify manifest segment count
        let manifestData = try Data(contentsOf: backup.manifestURL)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(RecordingBackupManifest.self, from: manifestData)
        XCTAssertEqual(manifest.segmentCount, 3)
        XCTAssertEqual(manifest.recordingType, "meeting")

        // Verify segments file contains all segments
        let segData = try Data(contentsOf: backup.segmentsFileURL)
        let decoded = try decoder.decode([LiveTranscriptSegment].self, from: segData)
        XCTAssertEqual(decoded.count, 3)
        XCTAssertEqual(decoded[0].text, "Good morning everyone.")
        XCTAssertEqual(decoded[1].text, "Thanks for joining.")
        XCTAssertEqual(decoded[2].text, "Let's get started.")
    }

    func testRemoveRecordingDeletesFiles() throws {
        let recordingId = "backup-remove-\(UUID().uuidString)"

        let backup = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "To be removed",
            recordingType: .reflection,
            durationSeconds: 10,
            transcript: "Some text",
            segments: [
                LiveTranscriptSegment(
                    text: "Some text",
                    speaker: nil,
                    isFinal: true,
                    startMs: 0,
                    endMs: 1000,
                    confidence: 0.99
                )
            ]
        )

        // Confirm files exist before removal
        XCTAssertTrue(FileManager.default.fileExists(atPath: backup.manifestURL.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: backup.segmentsFileURL.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: backup.directoryURL.path))

        try RecordingBackupStore.removeRecording(recordingId: recordingId)

        // Confirm everything is gone
        XCTAssertFalse(FileManager.default.fileExists(atPath: backup.manifestURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: backup.segmentsFileURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: backup.directoryURL.path))
    }

    func testRemoveRecordingForNonExistentRecordingDoesNotCrash() throws {
        let recordingId = "backup-nonexistent-\(UUID().uuidString)"

        // Should not throw — removeRecording guards with existingBackup which returns nil
        XCTAssertNoThrow(try RecordingBackupStore.removeRecording(recordingId: recordingId))
    }

    func testRemoveAllRecordingsDeletesEveryBackup() throws {
        _ = try RecordingBackupStore.saveRecording(
            recordingId: "backup-remove-all-1-\(UUID().uuidString)",
            title: "First",
            recordingType: .note,
            durationSeconds: 1,
            transcript: "First",
            segments: []
        )
        _ = try RecordingBackupStore.saveRecording(
            recordingId: "backup-remove-all-2-\(UUID().uuidString)",
            title: "Second",
            recordingType: .meeting,
            durationSeconds: 2,
            transcript: "Second",
            segments: []
        )

        XCTAssertEqual(try RecordingBackupStore.listBackups().count, 2)

        try RecordingBackupStore.removeAllRecordings()

        XCTAssertEqual(try RecordingBackupStore.listBackups(), [])
        XCTAssertFalse(FileManager.default.fileExists(atPath: backupRoot.path))
    }

    func testRecordSaveFailureForNonExistentRecordingReturnsNil() throws {
        let recordingId = "backup-no-exist-failure-\(UUID().uuidString)"

        let result = try RecordingBackupStore.recordSaveFailure(
            recordingId: recordingId,
            message: "Should return nil"
        )
        XCTAssertNil(result)
    }

    func testSaveRecordingPreservesAllSegmentFields() throws {
        let recordingId = "backup-fields-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        let segment = LiveTranscriptSegment(
            text: "Detailed segment",
            speaker: "Dr. Smith",
            isFinal: true,
            startMs: 1234,
            endMs: 5678,
            confidence: 0.9372
        )

        let backup = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Field preservation test",
            recordingType: .meeting,
            durationSeconds: 5.678,
            transcript: "Detailed segment",
            segments: [segment]
        )

        let segData = try Data(contentsOf: backup.segmentsFileURL)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode([LiveTranscriptSegment].self, from: segData)

        XCTAssertEqual(decoded.count, 1)
        let roundTripped = decoded[0]
        XCTAssertEqual(roundTripped.text, "Detailed segment")
        XCTAssertEqual(roundTripped.speaker, "Dr. Smith")
        XCTAssertEqual(roundTripped.isFinal, true)
        XCTAssertEqual(roundTripped.startMs, 1234)
        XCTAssertEqual(roundTripped.endMs, 5678)
        XCTAssertEqual(roundTripped.confidence, 0.9372, accuracy: 0.0001)
    }

    func testSaveRecordingPreservesManifestFields() throws {
        let recordingId = "backup-manifest-fields-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        let beforeSave = Date()

        let backup = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Manifest check",
            recordingType: .reflection,
            durationSeconds: 99.5,
            transcript: "Full transcript text here",
            segments: [
                LiveTranscriptSegment(
                    text: "A", speaker: nil, isFinal: true,
                    startMs: 0, endMs: 100, confidence: 0.5
                ),
                LiveTranscriptSegment(
                    text: "B", speaker: "Bob", isFinal: false,
                    startMs: 100, endMs: 200, confidence: 0.7
                ),
            ]
        )

        let manifestData = try Data(contentsOf: backup.manifestURL)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(RecordingBackupManifest.self, from: manifestData)

        XCTAssertEqual(manifest.recordingId, recordingId)
        XCTAssertEqual(manifest.title, "Manifest check")
        XCTAssertEqual(manifest.recordingType, "reflection")
        XCTAssertEqual(manifest.durationSeconds, 99.5, accuracy: 0.001)
        XCTAssertEqual(manifest.segmentCount, 2)
        XCTAssertEqual(manifest.transcript, "Full transcript text here")
        XCTAssertNil(manifest.lastErrorMessage)
        // ISO 8601 truncates sub-second precision, so allow 1 second tolerance
        XCTAssertEqual(
            manifest.createdAt.timeIntervalSince1970,
            beforeSave.timeIntervalSince1970,
            accuracy: 2.0,
            "createdAt should be close to save time"
        )
        XCTAssertEqual(
            manifest.updatedAt.timeIntervalSince1970,
            beforeSave.timeIntervalSince1970,
            accuracy: 2.0,
            "updatedAt should be close to save time"
        )
    }

    func testExistingBackupReturnsNilForUnknownRecording() throws {
        let recordingId = "backup-unknown-\(UUID().uuidString)"
        let result = try RecordingBackupStore.existingBackup(recordingId: recordingId)
        XCTAssertNil(result)
    }

    func testExistingBackupReturnsBackupAfterSave() throws {
        let recordingId = "backup-exists-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Exists",
            recordingType: .note,
            durationSeconds: 1,
            transcript: nil,
            segments: []
        )

        let result = try RecordingBackupStore.existingBackup(recordingId: recordingId)
        XCTAssertNotNil(result)
        XCTAssertEqual(result?.recordingId, recordingId)
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

    func testSaveRecordingPreservesExistingAudioFlag() throws {
        let recordingId = "backup-preserve-audio-flag-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Initial backup",
            recordingType: .note,
            durationSeconds: 3,
            transcript: "Initial",
            segments: []
        )
        try RecordingBackupStore.markHasAudioFile(recordingId: recordingId)

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Resaved backup",
            recordingType: .note,
            durationSeconds: 4,
            transcript: nil,
            segments: []
        )

        let manifest = try XCTUnwrap(RecordingBackupStore.manifest(recordingId: recordingId))
        XCTAssertTrue(manifest.hasAudioFile)
        XCTAssertEqual(manifest.title, "Resaved backup")
        XCTAssertEqual(manifest.durationSeconds, 4)
    }

    func testListBackupsReturnsAllSavedBackups() throws {
        let id1 = "backup-list-1-\(UUID().uuidString)"
        let id2 = "backup-list-2-\(UUID().uuidString)"
        let id3 = "backup-list-3-\(UUID().uuidString)"
        defer {
            try? RecordingBackupStore.removeRecording(recordingId: id1)
            try? RecordingBackupStore.removeRecording(recordingId: id2)
            try? RecordingBackupStore.removeRecording(recordingId: id3)
        }

        for id in [id1, id2, id3] {
            _ = try RecordingBackupStore.saveRecording(
                recordingId: id, title: "Backup \(id)", recordingType: .note,
                durationSeconds: 1, transcript: nil, segments: []
            )
        }

        let backups = try RecordingBackupStore.listBackups()
        let ourIds = Set([id1, id2, id3])
        let foundIds = Set(backups.map(\.recordingId).filter { ourIds.contains($0) })
        XCTAssertEqual(foundIds, ourIds, "All three backups should be listed")
    }

    func testListBackupsReturnsEmptyWhenNoBackupsExist() throws {
        let backups = try RecordingBackupStore.listBackups()
        XCTAssertTrue(backups.isEmpty)
    }

    func testSegmentsReturnsEmptyWhenFileNotFound() throws {
        let recordingId = "backup-no-segments-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        // Save with empty segments (no segments file created)
        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId, title: "No segments", recordingType: .note,
            durationSeconds: 1, transcript: nil, segments: []
        )

        let segments = try RecordingBackupStore.segments(recordingId: recordingId)
        XCTAssertTrue(segments.isEmpty)
    }

    func testMarkPermanentFailureOnNonExistentBackupDoesNotCrash() throws {
        let recordingId = "backup-no-exist-perm-\(UUID().uuidString)"
        XCTAssertNoThrow(try RecordingBackupStore.markPermanentFailure(recordingId: recordingId))
    }

    func testMarkAuthenticationRequiredUpdatesManifest() throws {
        let recordingId = "backup-auth-required-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Auth required",
            recordingType: .note,
            durationSeconds: 3,
            transcript: "Needs reauth",
            segments: []
        )

        try RecordingBackupStore.markAuthenticationRequired(recordingId: recordingId)

        let manifest = try XCTUnwrap(RecordingBackupStore.manifest(recordingId: recordingId))
        XCTAssertTrue(manifest.requiresAuthentication)
        XCTAssertFalse(manifest.isPermanentFailure)
    }

    func testClearAuthenticationRequiredRestoresRecoverableState() throws {
        let recordingId = "backup-auth-clear-\(UUID().uuidString)"
        defer { try? RecordingBackupStore.removeRecording(recordingId: recordingId) }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: "Auth clear",
            recordingType: .note,
            durationSeconds: 3,
            transcript: "Recoverable again",
            segments: []
        )

        try RecordingBackupStore.markAuthenticationRequired(recordingId: recordingId)
        try RecordingBackupStore.clearAuthenticationRequired(recordingId: recordingId)

        let manifest = try XCTUnwrap(RecordingBackupStore.manifest(recordingId: recordingId))
        XCTAssertFalse(manifest.requiresAuthentication)
        XCTAssertFalse(manifest.isPermanentFailure)
    }

    func testManifestsByRecordingIdReturnsAllManifests() throws {
        let id1 = "backup-manifests-1-\(UUID().uuidString)"
        let id2 = "backup-manifests-2-\(UUID().uuidString)"
        defer {
            try? RecordingBackupStore.removeRecording(recordingId: id1)
            try? RecordingBackupStore.removeRecording(recordingId: id2)
        }

        _ = try RecordingBackupStore.saveRecording(
            recordingId: id1, title: "First", recordingType: .note,
            durationSeconds: 1, transcript: nil, segments: []
        )
        _ = try RecordingBackupStore.saveRecording(
            recordingId: id2, title: "Second", recordingType: .meeting,
            durationSeconds: 2, transcript: "Hello", segments: []
        )

        let manifests = try RecordingBackupStore.manifestsByRecordingId()
        XCTAssertNotNil(manifests[id1])
        XCTAssertNotNil(manifests[id2])
        XCTAssertEqual(manifests[id1]?.title, "First")
        XCTAssertEqual(manifests[id2]?.title, "Second")
    }
}
