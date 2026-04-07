import Foundation
import XCTest
@testable import WaiSayKit

final class ModelTests: XCTestCase {

    /// Builds a decoder matching the APIClient configuration:
    /// custom date decoding supporting ISO8601 with and without fractional seconds.
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

    // MARK: - Recording Tests

    func testFolderDecodeFromJSON() throws {
        let json = """
        {
            "id": "folder-1",
            "name": "Projects",
            "created_at": "2026-01-15T10:30:00Z"
        }
        """.data(using: .utf8)!

        let folder = try makeDecoder().decode(Folder.self, from: json)
        XCTAssertEqual(folder.id, "folder-1")
        XCTAssertEqual(folder.name, "Projects")
    }

    func testRecordingDecodeFromJSON() throws {
        let json = """
        {
            "id": "rec-1",
            "title": "Sprint Planning",
            "type": "meeting",
            "audio_url": "https://storage.example.com/audio/rec-1.opus",
            "status": "failed",
            "failure_code": "file_too_large",
            "failure_message": "File too large",
            "uploaded_at": "2026-01-15T10:31:00Z",
            "duration_seconds": 3600,
            "language": "en",
            "folder_id": "folder-1",
            "deleted_at": null,
            "created_at": "2026-01-15T10:30:00.123Z"
        }
        """.data(using: .utf8)!

        let recording = try makeDecoder().decode(Recording.self, from: json)
        XCTAssertEqual(recording.id, "rec-1")
        XCTAssertEqual(recording.title, "Sprint Planning")
        XCTAssertEqual(recording.type, .meeting)
        XCTAssertEqual(recording.audioUrl, "https://storage.example.com/audio/rec-1.opus")
        XCTAssertEqual(recording.status, .failed)
        XCTAssertEqual(recording.failureCode, "file_too_large")
        XCTAssertEqual(recording.failureMessage, "File too large")
        XCTAssertNotNil(recording.uploadedAt)
        XCTAssertEqual(recording.durationSeconds, 3600)
        XCTAssertEqual(recording.language, "en")
        XCTAssertEqual(recording.folderId, "folder-1")
        XCTAssertNil(recording.deletedAt)
        XCTAssertNotNil(recording.createdAt)
    }

    func testRecordingEncodeToJSON() throws {
        let encoder = makeEncoder()
        let decoder = makeDecoder()

        let original = Recording(
            id: "rec-round",
            title: "Round Trip",
            type: .reflection,
            audioUrl: "https://example.com/audio.opus",
            durationSeconds: 120,
            language: "de",
            createdAt: Date(timeIntervalSince1970: 1704067200) // 2024-01-01T00:00:00Z
        )

        let data = try encoder.encode(original)
        let decoded = try decoder.decode(Recording.self, from: data)

        XCTAssertEqual(decoded.id, original.id)
        XCTAssertEqual(decoded.title, original.title)
        XCTAssertEqual(decoded.type, original.type)
        XCTAssertEqual(decoded.audioUrl, original.audioUrl)
        XCTAssertEqual(decoded.durationSeconds, original.durationSeconds)
        XCTAssertEqual(decoded.language, original.language)
        XCTAssertEqual(
            decoded.createdAt.timeIntervalSince1970,
            original.createdAt.timeIntervalSince1970,
            accuracy: 1
        )
    }

    func testRecordingDetailDecodeWithSegmentsAndSummary() throws {
        let json = """
        {
            "id": "rec-detail",
            "title": "Architecture Review",
            "type": "meeting",
            "duration_seconds": 1800,
            "created_at": "2026-02-01T14:00:00Z",
            "segments": [
                {
                    "id": "seg-1",
                    "speaker": "Alice",
                    "content": "Let us discuss the new architecture.",
                    "start_ms": 0,
                    "end_ms": 4000,
                    "confidence": 0.97
                },
                {
                    "id": "seg-2",
                    "content": "Sounds good.",
                    "start_ms": 4000,
                    "end_ms": 5500
                }
            ],
            "summary": {
                "summary": "Discussed new service architecture.",
                "key_points": ["Microservices migration", "API gateway"],
                "decisions": [
                    {"decision": "Use event-driven architecture", "context": "For async processing"}
                ],
                "topics": ["architecture", "microservices"],
                "people_mentioned": ["Alice", "Bob"],
                "sentiment": "positive"
            },
            "action_items": [
                {
                    "id": "ai-1",
                    "recording_id": "rec-detail",
                    "task": "Draft architecture document",
                    "owner": "Alice",
                    "due_date": "2026-02-15",
                    "priority": "high",
                    "status": "pending",
                    "created_at": "2026-02-01T14:30:00Z"
                }
            ]
        }
        """.data(using: .utf8)!

        let detail = try makeDecoder().decode(RecordingDetail.self, from: json)
        XCTAssertEqual(detail.id, "rec-detail")
        XCTAssertEqual(detail.title, "Architecture Review")
        XCTAssertEqual(detail.type, .meeting)
        XCTAssertEqual(detail.durationSeconds, 1800)

        // Segments
        XCTAssertEqual(detail.segments.count, 2)
        XCTAssertEqual(detail.segments[0].speaker, "Alice")
        XCTAssertEqual(detail.segments[0].content, "Let us discuss the new architecture.")
        XCTAssertEqual(detail.segments[0].confidence, 0.97)
        XCTAssertNil(detail.segments[1].speaker)
        XCTAssertNil(detail.segments[1].confidence)

        // Summary
        XCTAssertNotNil(detail.summary)
        XCTAssertEqual(detail.summary?.summary, "Discussed new service architecture.")
        XCTAssertEqual(detail.summary?.keyPoints, ["Microservices migration", "API gateway"])
        XCTAssertEqual(detail.summary?.decisions?.count, 1)
        XCTAssertEqual(detail.summary?.decisions?[0].decision, "Use event-driven architecture")
        XCTAssertEqual(detail.summary?.decisions?[0].context, "For async processing")
        XCTAssertEqual(detail.summary?.topics, ["architecture", "microservices"])
        XCTAssertEqual(detail.summary?.peopleMentioned, ["Alice", "Bob"])
        XCTAssertEqual(detail.summary?.sentiment, "positive")

        // Action items
        XCTAssertEqual(detail.actionItems.count, 1)
        XCTAssertEqual(detail.actionItems[0].task, "Draft architecture document")
        XCTAssertEqual(detail.actionItems[0].owner, "Alice")
        XCTAssertEqual(detail.actionItems[0].priority, .high)
        XCTAssertEqual(detail.actionItems[0].status, .pending)
    }

    // MARK: - Segment Tests

    func testSegmentDecodeWithOptionalFields() throws {
        // Full segment with all optional fields present
        let fullJSON = """
        {
            "id": "seg-full",
            "speaker": "Bob",
            "content": "Complete segment",
            "start_ms": 1000,
            "end_ms": 5000,
            "confidence": 0.92
        }
        """.data(using: .utf8)!

        let full = try makeDecoder().decode(Segment.self, from: fullJSON)
        XCTAssertEqual(full.id, "seg-full")
        XCTAssertEqual(full.speaker, "Bob")
        XCTAssertEqual(full.content, "Complete segment")
        XCTAssertEqual(full.startMs, 1000)
        XCTAssertEqual(full.endMs, 5000)
        XCTAssertEqual(full.confidence, 0.92)
        XCTAssertEqual(full.durationMs, 4000)
        XCTAssertEqual(full.formattedTimestamp, "00:01")

        // Minimal segment with only required fields
        let minimalJSON = """
        {
            "id": "seg-min",
            "content": "Minimal segment"
        }
        """.data(using: .utf8)!

        let minimal = try makeDecoder().decode(Segment.self, from: minimalJSON)
        XCTAssertEqual(minimal.id, "seg-min")
        XCTAssertEqual(minimal.content, "Minimal segment")
        XCTAssertNil(minimal.speaker)
        XCTAssertNil(minimal.startMs)
        XCTAssertNil(minimal.endMs)
        XCTAssertNil(minimal.confidence)
        XCTAssertNil(minimal.durationMs)
        XCTAssertEqual(minimal.formattedTimestamp, "--:--")
    }

    // MARK: - Summary Tests

    func testSummaryDecodeWithAllFields() throws {
        let json = """
        {
            "summary": "Team discussed Q1 roadmap priorities.",
            "key_points": ["Launch feature A", "Retire unused API"],
            "decisions": [
                {"decision": "Prioritize mobile app", "context": "Revenue impact"},
                {"decision": "Hire two engineers"}
            ],
            "topics": ["roadmap", "hiring", "mobile"],
            "people_mentioned": ["CTO", "PM"],
            "sentiment": "neutral"
        }
        """.data(using: .utf8)!

        let summary = try makeDecoder().decode(Summary.self, from: json)
        XCTAssertEqual(summary.summary, "Team discussed Q1 roadmap priorities.")
        XCTAssertEqual(summary.keyPoints?.count, 2)
        XCTAssertEqual(summary.keyPoints?[0], "Launch feature A")
        XCTAssertEqual(summary.decisions?.count, 2)
        XCTAssertEqual(summary.decisions?[0].decision, "Prioritize mobile app")
        XCTAssertEqual(summary.decisions?[0].context, "Revenue impact")
        XCTAssertNil(summary.decisions?[1].context)
        XCTAssertEqual(summary.topics, ["roadmap", "hiring", "mobile"])
        XCTAssertEqual(summary.peopleMentioned, ["CTO", "PM"])
        XCTAssertEqual(summary.sentiment, "neutral")
    }

    // MARK: - ActionItem Tests

    func testActionItemAllStatusAndPriorityCombinations() throws {
        // Test all Status raw values
        XCTAssertEqual(ActionItem.Status.pending.rawValue, "pending")
        XCTAssertEqual(ActionItem.Status.inProgress.rawValue, "in_progress")
        XCTAssertEqual(ActionItem.Status.completed.rawValue, "completed")
        XCTAssertEqual(ActionItem.Status.cancelled.rawValue, "cancelled")

        // Test all Priority raw values
        XCTAssertEqual(ActionItem.Priority.high.rawValue, "high")
        XCTAssertEqual(ActionItem.Priority.medium.rawValue, "medium")
        XCTAssertEqual(ActionItem.Priority.low.rawValue, "low")

        // Decode each status from JSON
        for status in ActionItem.Status.allCases {
            let json = """
            {
                "id": "ai-\(status.rawValue)",
                "task": "Task with status \(status.rawValue)",
                "status": "\(status.rawValue)",
                "recording_id": "rec-1"
            }
            """.data(using: .utf8)!

            let item = try makeDecoder().decode(ActionItem.self, from: json)
            XCTAssertEqual(item.status, status)
        }

        // Decode each priority from JSON
        for priority in ActionItem.Priority.allCases {
            let json = """
            {
                "id": "ai-\(priority.rawValue)",
                "task": "Task with priority \(priority.rawValue)",
                "status": "pending",
                "priority": "\(priority.rawValue)"
            }
            """.data(using: .utf8)!

            let item = try makeDecoder().decode(ActionItem.self, from: json)
            XCTAssertEqual(item.priority, priority)
        }
    }

    // MARK: - Entity Tests

    func testEntityDecodeWithMetadata() throws {
        let json = """
        {
            "id": "ent-1",
            "type": "person",
            "name": "Alice Johnson",
            "metadata": {
                "role": "Engineer",
                "team": "Backend"
            }
        }
        """.data(using: .utf8)!

        let entity = try makeDecoder().decode(Entity.self, from: json)
        XCTAssertEqual(entity.id, "ent-1")
        XCTAssertEqual(entity.type, .person)
        XCTAssertEqual(entity.name, "Alice Johnson")
        XCTAssertNotNil(entity.metadata)
        XCTAssertEqual(entity.metadata?["role"], "Engineer")
        XCTAssertEqual(entity.metadata?["team"], "Backend")

        // Entity without metadata
        let noMetaJSON = """
        {"id": "ent-2", "type": "topic", "name": "Architecture"}
        """.data(using: .utf8)!

        let noMeta = try makeDecoder().decode(Entity.self, from: noMetaJSON)
        XCTAssertNil(noMeta.metadata)
        XCTAssertEqual(noMeta.type, .topic)
    }

    func testEntityDetailDecodeWithRelations() throws {
        let json = """
        {
            "id": "ent-1",
            "type": "person",
            "name": "Alice",
            "metadata": {"department": "Engineering"},
            "relations": [
                {
                    "id": "rel-1",
                    "target_id": "ent-2",
                    "target_name": "Backend Redesign",
                    "target_type": "project",
                    "relation_type": "works_on",
                    "context": "Lead engineer on the project"
                },
                {
                    "id": "rel-2",
                    "target_id": "ent-3",
                    "target_name": "Acme Corp",
                    "target_type": "organization"
                }
            ]
        }
        """.data(using: .utf8)!

        let detail = try makeDecoder().decode(EntityDetail.self, from: json)
        XCTAssertEqual(detail.id, "ent-1")
        XCTAssertEqual(detail.type, .person)
        XCTAssertEqual(detail.name, "Alice")
        XCTAssertEqual(detail.metadata?["department"], "Engineering")
        XCTAssertEqual(detail.relations.count, 2)

        let rel1 = detail.relations[0]
        XCTAssertEqual(rel1.id, "rel-1")
        XCTAssertEqual(rel1.targetId, "ent-2")
        XCTAssertEqual(rel1.targetName, "Backend Redesign")
        XCTAssertEqual(rel1.targetType, .project)
        XCTAssertEqual(rel1.relationType, "works_on")
        XCTAssertEqual(rel1.context, "Lead engineer on the project")

        let rel2 = detail.relations[1]
        XCTAssertEqual(rel2.targetType, .organization)
        XCTAssertNil(rel2.relationType)
        XCTAssertNil(rel2.context)
    }

    // MARK: - SearchResult Tests

    func testSearchResultAndResponseDecode() throws {
        let json = """
        {
            "results": [
                {
                    "recording_id": "rec-1",
                    "recording_title": "Weekly Standup",
                    "recording_type": "meeting",
                    "segment_id": "seg-42",
                    "speaker": "Bob",
                    "content": "We need to finish the API redesign by Friday.",
                    "start_ms": 15000,
                    "end_ms": 22000,
                    "score": 0.93
                },
                {
                    "recording_id": "rec-2",
                    "recording_type": "note",
                    "segment_id": "seg-99",
                    "content": "API endpoint migration plan.",
                    "score": 0.71
                }
            ],
            "total": 2
        }
        """.data(using: .utf8)!

        let response = try makeDecoder().decode(SearchResponse.self, from: json)
        XCTAssertEqual(response.total, 2)
        XCTAssertEqual(response.results.count, 2)

        let first = response.results[0]
        XCTAssertEqual(first.recordingId, "rec-1")
        XCTAssertEqual(first.recordingTitle, "Weekly Standup")
        XCTAssertEqual(first.recordingType, .meeting)
        XCTAssertEqual(first.segmentId, "seg-42")
        XCTAssertEqual(first.id, "seg-42") // computed id == segmentId
        XCTAssertEqual(first.speaker, "Bob")
        XCTAssertEqual(first.content, "We need to finish the API redesign by Friday.")
        XCTAssertEqual(first.startMs, 15000)
        XCTAssertEqual(first.endMs, 22000)
        XCTAssertEqual(first.score, 0.93)

        let second = response.results[1]
        XCTAssertEqual(second.recordingType, .note)
        XCTAssertNil(second.recordingTitle)
        XCTAssertNil(second.speaker)
        XCTAssertNil(second.startMs)
        XCTAssertNil(second.endMs)
        XCTAssertEqual(second.score, 0.71)
    }
}
