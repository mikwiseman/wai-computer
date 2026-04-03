import Foundation
import XCTest
@testable import WaiComputerKit

final class NewFieldsModelTests: XCTestCase {

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

    // MARK: - Recording.starredAt

    func testRecordingDecodesStarredAtWhenPresent() throws {
        let json = """
        {
            "id": "rec-star-1",
            "title": "Starred Recording",
            "type": "note",
            "status": "ready",
            "starred_at": "2026-03-10T14:30:00Z",
            "created_at": "2026-03-01T09:00:00Z"
        }
        """.data(using: .utf8)!

        let recording = try makeDecoder().decode(Recording.self, from: json)
        XCTAssertEqual(recording.id, "rec-star-1")
        XCTAssertNotNil(recording.starredAt)

        let calendar = Calendar(identifier: .gregorian)
        var components = DateComponents()
        components.timeZone = TimeZone(identifier: "UTC")
        components.year = 2026
        components.month = 3
        components.day = 10
        components.hour = 14
        components.minute = 30
        let expectedDate = calendar.date(from: components)!
        XCTAssertEqual(
            recording.starredAt!.timeIntervalSince1970,
            expectedDate.timeIntervalSince1970,
            accuracy: 1
        )
    }

    func testRecordingDecodesStarredAtAsNilWhenAbsent() throws {
        let json = """
        {
            "id": "rec-no-star",
            "title": "Unstarred Recording",
            "type": "meeting",
            "status": "ready",
            "created_at": "2026-03-01T09:00:00Z"
        }
        """.data(using: .utf8)!

        let recording = try makeDecoder().decode(Recording.self, from: json)
        XCTAssertEqual(recording.id, "rec-no-star")
        XCTAssertNil(recording.starredAt)
    }

    func testRecordingDecodesStarredAtAsNilWhenExplicitNull() throws {
        let json = """
        {
            "id": "rec-null-star",
            "type": "reflection",
            "starred_at": null,
            "created_at": "2026-03-01T09:00:00Z"
        }
        """.data(using: .utf8)!

        let recording = try makeDecoder().decode(Recording.self, from: json)
        XCTAssertNil(recording.starredAt)
    }

    // MARK: - RecordingDetail.highlights

    func testRecordingDetailDecodesHighlightsArray() throws {
        let json = """
        {
            "id": "rec-hl",
            "type": "meeting",
            "created_at": "2026-03-05T10:00:00Z",
            "segments": [],
            "action_items": [],
            "highlights": [
                {
                    "id": "hl-1",
                    "recording_id": "rec-hl",
                    "category": "decision",
                    "title": "Chose microservices",
                    "description": "Team decided to adopt microservices architecture",
                    "speaker": "Alice",
                    "start_ms": 5000,
                    "end_ms": 12000,
                    "importance": "high"
                },
                {
                    "id": "hl-2",
                    "recording_id": "rec-hl",
                    "category": "action_item",
                    "title": "Create migration plan",
                    "importance": "medium"
                }
            ]
        }
        """.data(using: .utf8)!

        let detail = try makeDecoder().decode(RecordingDetail.self, from: json)
        XCTAssertEqual(detail.highlights.count, 2)

        let hl1 = detail.highlights[0]
        XCTAssertEqual(hl1.id, "hl-1")
        XCTAssertEqual(hl1.recordingId, "rec-hl")
        XCTAssertEqual(hl1.category, "decision")
        XCTAssertEqual(hl1.title, "Chose microservices")
        XCTAssertEqual(hl1.description, "Team decided to adopt microservices architecture")
        XCTAssertEqual(hl1.speaker, "Alice")
        XCTAssertEqual(hl1.startMs, 5000)
        XCTAssertEqual(hl1.endMs, 12000)
        XCTAssertEqual(hl1.importance, "high")

        let hl2 = detail.highlights[1]
        XCTAssertEqual(hl2.id, "hl-2")
        XCTAssertEqual(hl2.category, "action_item")
        XCTAssertNil(hl2.description)
        XCTAssertNil(hl2.speaker)
        XCTAssertNil(hl2.startMs)
        XCTAssertNil(hl2.endMs)
        XCTAssertEqual(hl2.importance, "medium")
    }

    func testRecordingDetailDecodesEmptyHighlightsArray() throws {
        let json = """
        {
            "id": "rec-no-hl",
            "type": "note",
            "created_at": "2026-03-05T10:00:00Z",
            "segments": [],
            "action_items": [],
            "highlights": []
        }
        """.data(using: .utf8)!

        let detail = try makeDecoder().decode(RecordingDetail.self, from: json)
        XCTAssertEqual(detail.highlights.count, 0)
    }

    func testRecordingDetailDefaultsHighlightsWhenKeyMissing() throws {
        let json = """
        {
            "id": "rec-missing-hl",
            "type": "note",
            "created_at": "2026-03-05T10:00:00Z",
            "segments": [],
            "action_items": []
        }
        """.data(using: .utf8)!

        let detail = try makeDecoder().decode(RecordingDetail.self, from: json)
        XCTAssertEqual(detail.highlights.count, 0)
    }

    // MARK: - RecordingHighlight

    func testRecordingHighlightDecodesAllFields() throws {
        let json = """
        {
            "id": "hl-full",
            "recording_id": "rec-99",
            "category": "key_insight",
            "title": "Revenue grew 30%",
            "description": "Q1 revenue exceeded projections by 30 percent",
            "speaker": "CFO",
            "start_ms": 45000,
            "end_ms": 52000,
            "importance": "high"
        }
        """.data(using: .utf8)!

        let hl = try makeDecoder().decode(RecordingHighlight.self, from: json)
        XCTAssertEqual(hl.id, "hl-full")
        XCTAssertEqual(hl.recordingId, "rec-99")
        XCTAssertEqual(hl.category, "key_insight")
        XCTAssertEqual(hl.title, "Revenue grew 30%")
        XCTAssertEqual(hl.description, "Q1 revenue exceeded projections by 30 percent")
        XCTAssertEqual(hl.speaker, "CFO")
        XCTAssertEqual(hl.startMs, 45000)
        XCTAssertEqual(hl.endMs, 52000)
        XCTAssertEqual(hl.importance, "high")
    }

    // MARK: - ChatSessionListItem.pinnedAt

    func testChatSessionListItemDecodesPinnedAtWhenPresent() throws {
        let json = """
        {
            "id": "session-pin-1",
            "title": "Pinned Chat",
            "created_at": "2026-03-10T08:00:00Z",
            "message_count": 5,
            "pinned_at": "2026-03-12T16:45:00Z"
        }
        """.data(using: .utf8)!

        let session = try makeDecoder().decode(ChatSessionListItem.self, from: json)
        XCTAssertEqual(session.id, "session-pin-1")
        XCTAssertEqual(session.title, "Pinned Chat")
        XCTAssertEqual(session.messageCount, 5)
        XCTAssertNotNil(session.pinnedAt)
        XCTAssertEqual(session.pinnedAt, "2026-03-12T16:45:00Z")
    }

    func testChatSessionListItemDecodesPinnedAtAsNilWhenAbsent() throws {
        let json = """
        {
            "id": "session-no-pin",
            "title": "Regular Chat",
            "created_at": "2026-03-10T08:00:00Z",
            "message_count": 3
        }
        """.data(using: .utf8)!

        let session = try makeDecoder().decode(ChatSessionListItem.self, from: json)
        XCTAssertEqual(session.id, "session-no-pin")
        XCTAssertNil(session.pinnedAt)
    }

    func testChatSessionListItemDecodesPinnedAtAsNilWhenExplicitNull() throws {
        let json = """
        {
            "id": "session-null-pin",
            "created_at": "2026-03-10T08:00:00Z",
            "message_count": 0,
            "pinned_at": null
        }
        """.data(using: .utf8)!

        let session = try makeDecoder().decode(ChatSessionListItem.self, from: json)
        XCTAssertNil(session.pinnedAt)
    }

    // MARK: - Round-trip encode/decode

    func testRecordingRoundTripPreservesStarredAt() throws {
        let encoder = makeEncoder()
        let decoder = makeDecoder()

        let starDate = Date(timeIntervalSince1970: 1_773_000_000) // ~2026-03-06
        let original = Recording(
            id: "rec-rt-star",
            title: "Round Trip Starred",
            type: .meeting,
            starredAt: starDate,
            createdAt: Date(timeIntervalSince1970: 1_772_000_000)
        )

        let data = try encoder.encode(original)
        let decoded = try decoder.decode(Recording.self, from: data)

        XCTAssertEqual(decoded.id, original.id)
        XCTAssertEqual(decoded.title, original.title)
        XCTAssertNotNil(decoded.starredAt)
        XCTAssertEqual(
            decoded.starredAt!.timeIntervalSince1970,
            original.starredAt!.timeIntervalSince1970,
            accuracy: 1
        )
    }

    func testRecordingRoundTripPreservesNilStarredAt() throws {
        let encoder = makeEncoder()
        let decoder = makeDecoder()

        let original = Recording(
            id: "rec-rt-no-star",
            title: "Round Trip No Star",
            type: .note,
            createdAt: Date(timeIntervalSince1970: 1_772_000_000)
        )

        let data = try encoder.encode(original)
        let decoded = try decoder.decode(Recording.self, from: data)

        XCTAssertEqual(decoded.id, original.id)
        XCTAssertNil(decoded.starredAt)
    }

    func testRecordingDetailWithHighlightsRoundTrip() throws {
        let encoder = makeEncoder()
        let decoder = makeDecoder()

        let original = RecordingDetail(
            id: "rec-rt-hl",
            title: "Highlights Round Trip",
            type: .reflection,
            starredAt: Date(timeIntervalSince1970: 1_773_000_000),
            createdAt: Date(timeIntervalSince1970: 1_772_000_000),
            segments: [],
            summary: nil,
            actionItems: [],
            highlights: [
                RecordingHighlight(
                    id: "hl-rt-1",
                    recordingId: "rec-rt-hl",
                    category: "decision",
                    title: "Chose Postgres",
                    description: "Decided on PostgreSQL for the database",
                    speaker: "CTO",
                    startMs: 1000,
                    endMs: 5000,
                    importance: "high"
                )
            ]
        )

        let data = try encoder.encode(original)
        let decoded = try decoder.decode(RecordingDetail.self, from: data)

        XCTAssertEqual(decoded.id, original.id)
        XCTAssertEqual(decoded.highlights.count, 1)
        XCTAssertEqual(decoded.highlights[0].id, "hl-rt-1")
        XCTAssertEqual(decoded.highlights[0].category, "decision")
        XCTAssertEqual(decoded.highlights[0].title, "Chose Postgres")
        XCTAssertEqual(decoded.highlights[0].description, "Decided on PostgreSQL for the database")
        XCTAssertEqual(decoded.highlights[0].speaker, "CTO")
        XCTAssertEqual(decoded.highlights[0].startMs, 1000)
        XCTAssertEqual(decoded.highlights[0].endMs, 5000)
        XCTAssertEqual(decoded.highlights[0].importance, "high")
        XCTAssertNotNil(decoded.starredAt)
    }

    // MARK: - ChatSessionDetail with messages

    func testChatSessionDetailDecodesWithMessages() throws {
        let json = """
        {
            "id": "session-detail-1",
            "title": "Deep Dive Chat",
            "recording_ids": ["rec-1", "rec-2"],
            "created_at": "2026-03-10T08:00:00Z",
            "messages": [
                {
                    "id": "msg-1",
                    "role": "user",
                    "content": "What were the key decisions?",
                    "created_at": "2026-03-10T08:01:00Z"
                },
                {
                    "id": "msg-2",
                    "role": "assistant",
                    "content": "Based on the recordings, the team decided to migrate to microservices.",
                    "source_segment_ids": ["seg-10", "seg-15"],
                    "source_recording_ids": ["rec-1"],
                    "created_at": "2026-03-10T08:01:05Z"
                }
            ]
        }
        """.data(using: .utf8)!

        let detail = try makeDecoder().decode(ChatSessionDetail.self, from: json)
        XCTAssertEqual(detail.id, "session-detail-1")
        XCTAssertEqual(detail.title, "Deep Dive Chat")
        XCTAssertEqual(detail.recordingIds, ["rec-1", "rec-2"])
        XCTAssertEqual(detail.messages.count, 2)

        let userMsg = detail.messages[0]
        XCTAssertEqual(userMsg.id, "msg-1")
        XCTAssertEqual(userMsg.role, "user")
        XCTAssertEqual(userMsg.content, "What were the key decisions?")
        XCTAssertNil(userMsg.sourceSegmentIds)

        let assistantMsg = detail.messages[1]
        XCTAssertEqual(assistantMsg.id, "msg-2")
        XCTAssertEqual(assistantMsg.role, "assistant")
        XCTAssertEqual(assistantMsg.sourceSegmentIds, ["seg-10", "seg-15"])
        XCTAssertEqual(assistantMsg.sourceRecordingIds, ["rec-1"])
    }

    // MARK: - UserApp lifecycle

    func testUserAppDecodesLifecycleFields() throws {
        let json = """
        {
            "id": "app-42",
            "name": "habits",
            "display_name": "Habit Tracker",
            "description": "Tracks daily habits",
            "icon": "✅",
            "template": "tracker",
            "schema_def": { "habit": "string" },
            "app_url": "https://habits.wai.computer",
            "settings": { "theme": "calm" },
            "status": "live",
            "visibility": "public",
            "published_at": "2026-04-01T12:00:00Z",
            "last_used_at": "2026-04-01T13:00:00Z",
            "sort_order": 2,
            "item_count": 12,
            "created_at": "2026-03-20T09:00:00Z"
        }
        """.data(using: .utf8)!

        let app = try makeDecoder().decode(UserApp.self, from: json)
        XCTAssertEqual(app.id, "app-42")
        XCTAssertEqual(app.description, "Tracks daily habits")
        XCTAssertEqual(app.status, .live)
        XCTAssertEqual(app.visibility, .public)
        XCTAssertEqual(app.itemCount, 12)
        XCTAssertNotNil(app.publishedAt)
        XCTAssertNotNil(app.lastUsedAt)
    }
}
