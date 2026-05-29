import Foundation
import XCTest
@testable import WaiComputerKit

final class ModelEdgeCaseTests: XCTestCase {

    // MARK: - Helpers

    private func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)

            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: dateString) {
                return date
            }

            formatter.formatOptions = [.withInternetDateTime]
            if let date = formatter.date(from: dateString) {
                return date
            }

            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode date: \(dateString)"
            )
        }
        return decoder
    }

    private func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }

    // MARK: - RecordingStatus Decoding

    func testRecordingStatusDecodesPendingUpload() throws {
        let json = """
        {
            "id": "rec-status-1",
            "type": "note",
            "status": "pending_upload",
            "created_at": "2026-01-01T00:00:00Z"
        }
        """.data(using: .utf8)!

        let recording = try makeDecoder().decode(Recording.self, from: json)
        XCTAssertEqual(recording.status, .pendingUpload)
    }

    func testRecordingStatusDecodesProcessing() throws {
        let json = """
        {
            "id": "rec-status-2",
            "type": "meeting",
            "status": "processing",
            "created_at": "2026-01-01T00:00:00Z"
        }
        """.data(using: .utf8)!

        let recording = try makeDecoder().decode(Recording.self, from: json)
        XCTAssertEqual(recording.status, .processing)
    }

    func testRecordingStatusDecodesFailed() throws {
        let json = """
        {
            "id": "rec-status-3",
            "type": "reflection",
            "status": "failed",
            "created_at": "2026-01-01T00:00:00Z"
        }
        """.data(using: .utf8)!

        let recording = try makeDecoder().decode(Recording.self, from: json)
        XCTAssertEqual(recording.status, .failed)
    }

    // MARK: - RecordingStatus Unknown Value Throws

    func testRecordingStatusThrowsOnUnknownValue() {
        let json = """
        {
            "id": "rec-unknown-status",
            "type": "note",
            "status": "some_future_status_value",
            "created_at": "2026-01-01T00:00:00Z"
        }
        """.data(using: .utf8)!

        XCTAssertThrowsError(try makeDecoder().decode(Recording.self, from: json))
    }

    func testRecordingStatusThrowsOnEmptyString() {
        let json = """
        {
            "id": "rec-empty-status",
            "type": "note",
            "status": "",
            "created_at": "2026-01-01T00:00:00Z"
        }
        """.data(using: .utf8)!

        XCTAssertThrowsError(try makeDecoder().decode(Recording.self, from: json))
    }

    // MARK: - Recording With All Null Optional Fields

    func testRecordingDecodesWithAllNullOptionalFields() throws {
        let json = """
        {
            "id": "rec-bare",
            "type": "note",
            "title": null,
            "audio_url": null,
            "status": null,
            "failure_code": null,
            "failure_message": null,
            "uploaded_at": null,
            "duration_seconds": null,
            "language": null,
            "folder_id": null,
            "deleted_at": null,
            "starred_at": null,
            "created_at": "2026-01-01T00:00:00Z"
        }
        """.data(using: .utf8)!

        let recording = try makeDecoder().decode(Recording.self, from: json)
        XCTAssertEqual(recording.id, "rec-bare")
        XCTAssertEqual(recording.type, .note)
        XCTAssertNil(recording.title)
        XCTAssertNil(recording.audioUrl)
        // When status key is present but null, defaults to .pendingUpload
        XCTAssertEqual(recording.status, .pendingUpload)
        XCTAssertNil(recording.failureCode)
        XCTAssertNil(recording.failureMessage)
        XCTAssertNil(recording.uploadedAt)
        XCTAssertNil(recording.durationSeconds)
        XCTAssertNil(recording.language)
        XCTAssertNil(recording.folderId)
        XCTAssertNil(recording.deletedAt)
        XCTAssertNil(recording.starredAt)
    }

    func testRecordingDecodesWithMissingOptionalFields() throws {
        let json = """
        {
            "id": "rec-minimal",
            "type": "meeting",
            "created_at": "2026-06-15T12:00:00Z"
        }
        """.data(using: .utf8)!

        let recording = try makeDecoder().decode(Recording.self, from: json)
        XCTAssertEqual(recording.id, "rec-minimal")
        XCTAssertEqual(recording.type, .meeting)
        XCTAssertNil(recording.title)
        XCTAssertNil(recording.audioUrl)
        // When status key is missing entirely, defaults to .pendingUpload
        XCTAssertEqual(recording.status, .pendingUpload)
        XCTAssertNil(recording.failureCode)
        XCTAssertNil(recording.failureMessage)
        XCTAssertNil(recording.uploadedAt)
        XCTAssertNil(recording.durationSeconds)
        XCTAssertNil(recording.language)
        XCTAssertNil(recording.folderId)
        XCTAssertNil(recording.deletedAt)
        XCTAssertNil(recording.starredAt)
    }

    // MARK: - RecordingDetail With Empty / Missing Collections

    func testRecordingDetailDecodesWithEmptySegmentsNoSummaryNoActionItemsNoHighlights() throws {
        let json = """
        {
            "id": "rec-empty-detail",
            "type": "reflection",
            "created_at": "2026-02-20T09:00:00Z",
            "segments": [],
            "summary": null,
            "action_items": [],
            "highlights": []
        }
        """.data(using: .utf8)!

        let detail = try makeDecoder().decode(RecordingDetail.self, from: json)
        XCTAssertEqual(detail.id, "rec-empty-detail")
        XCTAssertEqual(detail.type, .reflection)
        XCTAssertTrue(detail.segments.isEmpty)
        XCTAssertNil(detail.summary)
        XCTAssertTrue(detail.actionItems.isEmpty)
        XCTAssertTrue(detail.highlights.isEmpty)
    }

    func testRecordingDetailDecodesWithMissingCollectionKeys() throws {
        let json = """
        {
            "id": "rec-no-collections",
            "type": "note",
            "created_at": "2026-02-20T09:00:00Z"
        }
        """.data(using: .utf8)!

        let detail = try makeDecoder().decode(RecordingDetail.self, from: json)
        XCTAssertEqual(detail.id, "rec-no-collections")
        XCTAssertTrue(detail.segments.isEmpty)
        XCTAssertNil(detail.summary)
        XCTAssertTrue(detail.actionItems.isEmpty)
        XCTAssertTrue(detail.highlights.isEmpty)
    }

    // MARK: - CreateRecordingRequest Encoding (snake_case keys)

    func testCreateRecordingRequestEncodesWithSnakeCaseKeys() throws {
        let request = CreateRecordingRequest(
            title: "Test Recording",
            type: .meeting,
            language: "de",
            folderId: "folder-42"
        )

        let data = try makeEncoder().encode(request)
        let jsonObject = try JSONSerialization.jsonObject(with: data) as! [String: Any]

        // Verify snake_case keys are used
        XCTAssertEqual(jsonObject["title"] as? String, "Test Recording")
        XCTAssertEqual(jsonObject["type"] as? String, "meeting")
        XCTAssertEqual(jsonObject["language"] as? String, "de")
        XCTAssertEqual(jsonObject["folder_id"] as? String, "folder-42")

        // Verify camelCase keys are NOT present
        XCTAssertNil(jsonObject["folderId"])
    }

    func testCreateRecordingRequestEncodesWithNilOptionalFields() throws {
        let request = CreateRecordingRequest(
            title: nil,
            type: .note,
            language: "en",
            folderId: nil
        )

        let data = try makeEncoder().encode(request)
        let jsonObject = try JSONSerialization.jsonObject(with: data) as! [String: Any]

        XCTAssertEqual(jsonObject["type"] as? String, "note")
        XCTAssertEqual(jsonObject["language"] as? String, "en")
        // nil optionals should not appear in the JSON at all (default Codable behavior)
        // or appear as null -- either way folder_id shouldn't have a string value
        XCTAssertNil(jsonObject["folder_id"] as? String)
    }

    // MARK: - Recording.isFailedUpload

    func testIsFailedUploadTrueWhenStatusFailed() {
        let recording = Recording(
            id: "rec-fail-1",
            type: .note,
            status: .failed
        )
        XCTAssertTrue(recording.isFailedUpload)
    }

    func testIsFailedUploadFalseWhenReadyEvenWithFailureMessage() {
        let recording = Recording(
            id: "rec-fail-2",
            type: .note,
            status: .ready,
            failureMessage: "Network timeout"
        )
        XCTAssertFalse(recording.isFailedUpload)
    }

    func testIsFailedUploadFalseWhenReadyAndNoFailureMessage() {
        let recording = Recording(
            id: "rec-ok",
            type: .meeting,
            status: .ready
        )
        XCTAssertFalse(recording.isFailedUpload)
    }

    func testIsFailedUploadFalseWhenFailureMessageIsEmpty() {
        let recording = Recording(
            id: "rec-empty-msg",
            type: .note,
            status: .processing,
            failureMessage: ""
        )
        XCTAssertFalse(recording.isFailedUpload)
    }

    func testIsFailedUploadOnlyTrueForFailedStatus() {
        let allStatuses: [RecordingStatus] = [.pendingUpload, .uploading, .processing, .ready, .failed]
        for status in allStatuses {
            let recording = Recording(
                id: "rec-status-check-\(status.rawValue)",
                type: .note,
                status: status,
                failureMessage: "Some stale error"
            )
            if status == .failed {
                XCTAssertTrue(recording.isFailedUpload, "\(status.rawValue) should be failed")
            } else {
                XCTAssertFalse(recording.isFailedUpload, "\(status.rawValue) should NOT be failed even with failureMessage")
            }
        }
    }

    // MARK: - Recording.statusDisplayText

    func testStatusDisplayTextForEachStatus() {
        let cases: [(RecordingStatus, String?)] = [
            (.failed, "Needs attention"),
            (.pendingUpload, "Waiting to sync"),
            (.uploading, "Syncing in background"),
            (.processing, "Processing"),
            (.ready, nil),
        ]

        for (status, expectedText) in cases {
            let recording = Recording(
                id: "rec-display-\(status.rawValue)",
                type: .note,
                status: status
            )
            XCTAssertEqual(
                recording.statusDisplayText,
                expectedText,
                "statusDisplayText mismatch for status \(status.rawValue)"
            )
        }
    }

    func testStatusDisplayTextUsesRussianWhenRequested() {
        let cases: [(RecordingStatus, String?)] = [
            (.failed, "Нужно внимание"),
            (.pendingUpload, "Ждет синхронизации"),
            (.uploading, "Синхронизируется в фоне"),
            (.processing, "Обрабатывается"),
            (.ready, nil),
        ]

        for (status, expectedText) in cases {
            let recording = Recording(
                id: "rec-display-ru-\(status.rawValue)",
                type: .note,
                status: status,
                language: "ru"
            )
            XCTAssertEqual(
                recording.statusDisplayText(languageCode: recording.language),
                expectedText,
                "Russian statusDisplayText mismatch for status \(status.rawValue)"
            )
        }
    }

    func testStatusDisplayTextUsesSavedLocallyOnlyForRecoveryBackup() {
        let recording = Recording(
            id: "rec-local-recovery",
            type: .note,
            status: .pendingUpload
        )

        XCTAssertEqual(
            recording.statusDisplayText(hasLocalRecoveryBackup: true),
            "Saved locally"
        )
        XCTAssertEqual(
            recording.statusDisplayText(hasLocalRecoveryBackup: true, languageCode: "ru"),
            "Сохранено локально"
        )
    }

    func testStatusDisplayTextPermanentLocalFailureOverridesSavedLocally() {
        // The exact stuck-recording scenario: server row still pending_upload,
        // a local backup exists, but the backup is a permanent failure. Must
        // surface as "needs attention", not the reassuring "saved locally".
        let recording = Recording(
            id: "rec-permanent-local-failure",
            type: .meeting,
            status: .pendingUpload
        )

        XCTAssertEqual(
            recording.statusDisplayText(
                hasLocalRecoveryBackup: true,
                hasPermanentLocalFailure: true
            ),
            "Needs attention"
        )
        XCTAssertEqual(
            recording.statusDisplayText(
                hasLocalRecoveryBackup: true,
                hasPermanentLocalFailure: true,
                languageCode: "ru"
            ),
            "Нужно внимание"
        )
    }

    // MARK: - Recording.failurePreviewText

    func testFailurePreviewTextReturnsNilWhenNoFailureMessage() {
        let recording = Recording(id: "rec-no-fail", type: .note)
        XCTAssertNil(recording.failurePreviewText)
    }

    func testFailurePreviewTextReturnsNilWhenFailureMessageEmpty() {
        let recording = Recording(id: "rec-empty-fail", type: .note, failureMessage: "")
        XCTAssertNil(recording.failurePreviewText)
    }

    func testFailurePreviewTextReturnsFullMessageWhenShort() {
        let shortMessage = "File not found"
        let recording = Recording(
            id: "rec-short-fail",
            type: .note,
            failureMessage: shortMessage
        )
        XCTAssertEqual(recording.failurePreviewText, shortMessage)
    }

    func testFailurePreviewTextReturnsMessageAtExactly90Chars() {
        let exactly90 = String(repeating: "x", count: 90)
        let recording = Recording(
            id: "rec-exact-fail",
            type: .note,
            failureMessage: exactly90
        )
        XCTAssertEqual(recording.failurePreviewText, exactly90)
        XCTAssertEqual(recording.failurePreviewText?.count, 90)
    }

    func testFailurePreviewTextTruncatesAt90CharsWithEllipsis() {
        let longMessage = String(repeating: "A", count: 150)
        let recording = Recording(
            id: "rec-long-fail",
            type: .note,
            failureMessage: longMessage
        )
        let preview = recording.failurePreviewText!
        XCTAssertEqual(preview.count, 90) // 87 chars + "..."
        XCTAssertTrue(preview.hasSuffix("..."))
        XCTAssertEqual(preview, String(repeating: "A", count: 87) + "...")
    }

    func testFailurePreviewTextReplacesNewlinesWithSpaces() {
        let multilineMessage = "Line one\nLine two\nLine three"
        let recording = Recording(
            id: "rec-newline-fail",
            type: .note,
            failureMessage: multilineMessage
        )
        let preview = recording.failurePreviewText!
        XCTAssertFalse(preview.contains("\n"))
        XCTAssertEqual(preview, "Line one Line two Line three")
    }

    func testFailurePreviewTextHidesTechnicalMessages() {
        let recording = Recording(
            id: "rec-technical-fail",
            type: .note,
            failureMessage: "Internal Server Error"
        )

        XCTAssertEqual(
            recording.failurePreviewText,
            "We couldn't finish saving your recording right now. Please try again in a moment."
        )
    }

    func testFailurePreviewTextTruncatesAfterNewlineNormalization() {
        // Build a message that is under 90 chars with newlines but over 90 when
        // newlines are replaced with spaces (same length, so just make it long enough).
        let longWithNewlines = String(repeating: "word\n", count: 25) // 125 chars
        let recording = Recording(
            id: "rec-long-nl-fail",
            type: .note,
            failureMessage: longWithNewlines
        )
        let preview = recording.failurePreviewText!
        XCTAssertEqual(preview.count, 90)
        XCTAssertTrue(preview.hasSuffix("..."))
        XCTAssertFalse(preview.contains("\n"))
    }
}
