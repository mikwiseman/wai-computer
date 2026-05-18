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

    // MARK: - Segment editable-speaker fields

    func testSegmentDecodesPersonAssignmentFields() throws {
        let json = """
        {
            "id": "seg-1",
            "speaker": "Speaker 0",
            "raw_label": "Speaker 0",
            "person_id": "person-uuid-1",
            "display_name": "Vasya",
            "auto_assigned": true,
            "match_confidence": 0.87,
            "content": "Hello world",
            "start_ms": 1000,
            "end_ms": 2000,
            "confidence": 0.95
        }
        """.data(using: .utf8)!

        let segment = try JSONDecoder().decode(Segment.self, from: json)
        XCTAssertEqual(segment.rawLabel, "Speaker 0")
        XCTAssertEqual(segment.personId, "person-uuid-1")
        XCTAssertEqual(segment.displayName, "Vasya")
        XCTAssertTrue(segment.autoAssigned)
        XCTAssertEqual(segment.matchConfidence ?? 0, 0.87, accuracy: 0.001)
    }

    func testSegmentDefaultsAutoAssignedToFalseWhenAbsent() throws {
        let json = """
        {
            "id": "seg-legacy",
            "speaker": "Speaker 0",
            "content": "hi"
        }
        """.data(using: .utf8)!

        let segment = try JSONDecoder().decode(Segment.self, from: json)
        XCTAssertFalse(segment.autoAssigned)
        XCTAssertNil(segment.rawLabel)
        XCTAssertNil(segment.personId)
        XCTAssertNil(segment.displayName)
        XCTAssertNil(segment.matchConfidence)
    }

    func testPersonDecodes() throws {
        let json = """
        {
            "id": "person-1",
            "display_name": "Vasya",
            "color": "#4f46e5",
            "aliases": ["Vasily"],
            "voiceprint_count": 3,
            "created_at": "2026-05-18T10:00:00Z",
            "updated_at": "2026-05-18T10:00:00Z"
        }
        """.data(using: .utf8)!

        let person = try JSONDecoder().decode(Person.self, from: json)
        XCTAssertEqual(person.displayName, "Vasya")
        XCTAssertEqual(person.color, "#4f46e5")
        XCTAssertEqual(person.aliases ?? [], ["Vasily"])
        XCTAssertEqual(person.voiceprintCount, 3)
    }

    // MARK: - VoiceEnrollmentResponse

    func testVoiceEnrollmentResponseDecodes() throws {
        let json = """
        {
            "person": {
                "id": "person-1",
                "display_name": "You",
                "color": null,
                "aliases": null,
                "voiceprint_count": 1,
                "created_at": "2026-05-19T12:00:00Z",
                "updated_at": "2026-05-19T12:00:00Z"
            },
            "voiceprint_id": "vp-1",
            "duration_s": 21.5
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(VoiceEnrollmentResponse.self, from: json)
        XCTAssertEqual(response.person.displayName, "You")
        XCTAssertEqual(response.voiceprintId, "vp-1")
        XCTAssertEqual(response.durationS, 21.5, accuracy: 0.001)
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

}
