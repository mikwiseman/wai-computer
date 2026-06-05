import XCTest
@testable import WaiComputerKit

final class CompanionModelsTests: XCTestCase {

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    // MARK: - CompanionScope

    func testCompanionScopeRoundTrip() throws {
        let scope = CompanionScope(
            recordingIds: ["rec-1", "rec-2"],
            brainSpaceId: "brain-1",
            folderIds: ["f-1"],
            types: ["meeting"],
            speakers: ["alice"],
            dateFrom: Date(timeIntervalSince1970: 1_700_000_000),
            dateTo: Date(timeIntervalSince1970: 1_700_001_000)
        )

        let data = try encoder.encode(scope)
        let decoded = try decoder.decode(CompanionScope.self, from: data)

        XCTAssertEqual(decoded, scope)
    }

    func testCompanionScopeDecodesFromSnakeCase() throws {
        let json = """
        {"recording_ids": ["a"], "brain_space_id": "brain-1", "folder_ids": ["f"], "types": ["t"], "speakers": ["s"]}
        """.data(using: .utf8)!

        let scope = try decoder.decode(CompanionScope.self, from: json)
        XCTAssertEqual(scope.recordingIds, ["a"])
        XCTAssertEqual(scope.brainSpaceId, "brain-1")
        XCTAssertEqual(scope.folderIds, ["f"])
        XCTAssertEqual(scope.types, ["t"])
        XCTAssertEqual(scope.speakers, ["s"])
        XCTAssertNil(scope.dateFrom)
        XCTAssertNil(scope.dateTo)
    }

    func testCompanionScopeAllFieldsOptional() throws {
        let json = "{}".data(using: .utf8)!
        let scope = try decoder.decode(CompanionScope.self, from: json)
        XCTAssertNil(scope.recordingIds)
        XCTAssertNil(scope.brainSpaceId)
        XCTAssertNil(scope.folderIds)
        XCTAssertNil(scope.types)
        XCTAssertNil(scope.speakers)
        XCTAssertNil(scope.dateFrom)
        XCTAssertNil(scope.dateTo)
    }

    // MARK: - CompanionMessageRole

    func testRoleRawValues() throws {
        XCTAssertEqual(CompanionMessageRole.user.rawValue, "user")
        XCTAssertEqual(CompanionMessageRole.assistant.rawValue, "assistant")
        XCTAssertEqual(CompanionMessageRole.tool.rawValue, "tool")

        let userJSON = "\"user\"".data(using: .utf8)!
        let role = try decoder.decode(CompanionMessageRole.self, from: userJSON)
        XCTAssertEqual(role, .user)
    }

    // MARK: - CompanionContent

    func testContentDecodesString() throws {
        let json = "\"hello world\"".data(using: .utf8)!
        let content = try decoder.decode(CompanionContent.self, from: json)
        guard case .text(let value) = content else {
            XCTFail("expected .text")
            return
        }
        XCTAssertEqual(value, "hello world")
    }

    func testContentDecodesBlocks() throws {
        let json = """
        [{"type": "text", "text": "hi"}, {"type": "text", "text": "there"}]
        """.data(using: .utf8)!
        let content = try decoder.decode(CompanionContent.self, from: json)
        guard case .blocks(let blocks) = content else {
            XCTFail("expected .blocks")
            return
        }
        XCTAssertEqual(blocks.count, 2)
        XCTAssertEqual(blocks[0]["text"]?.stringValue, "hi")
        XCTAssertEqual(blocks[1]["text"]?.stringValue, "there")
    }

    func testContentRoundTripText() throws {
        let original = CompanionContent.text("round trip")
        let data = try encoder.encode(original)
        let decoded = try decoder.decode(CompanionContent.self, from: data)
        XCTAssertEqual(decoded, original)
    }

    func testContentRoundTripBlocks() throws {
        let blocks: [[String: CompanionJSONValue]] = [
            ["type": .string("text"), "text": .string("a")],
            ["type": .string("text"), "text": .string("b")]
        ]
        let original = CompanionContent.blocks(blocks)
        let data = try encoder.encode(original)
        let decoded = try decoder.decode(CompanionContent.self, from: data)
        XCTAssertEqual(decoded, original)
    }

    // MARK: - CompanionJSONValue

    func testJSONValueDecodingAllTypes() throws {
        let cases: [(String, CompanionJSONValue)] = [
            ("null", .null),
            ("true", .bool(true)),
            ("false", .bool(false)),
            ("42", .int(42)),
            ("3.14", .double(3.14)),
            ("\"hi\"", .string("hi")),
            ("[1, 2, 3]", .array([.int(1), .int(2), .int(3)])),
            ("{\"a\": 1}", .object(["a": .int(1)]))
        ]

        for (json, expected) in cases {
            let data = json.data(using: .utf8)!
            let value = try decoder.decode(CompanionJSONValue.self, from: data)
            XCTAssertEqual(value, expected, "for \(json)")
        }
    }

    func testJSONValueEncodingAllTypes() throws {
        let values: [CompanionJSONValue] = [
            .null,
            .bool(true),
            .int(42),
            .double(3.5),
            .string("hi"),
            .array([.int(1), .string("two")]),
            .object(["k": .bool(false)])
        ]

        for value in values {
            let data = try encoder.encode(value)
            let decoded = try decoder.decode(CompanionJSONValue.self, from: data)
            XCTAssertEqual(decoded, value)
        }
    }

    func testStringValueAccessor() {
        XCTAssertEqual(CompanionJSONValue.string("hi").stringValue, "hi")
        XCTAssertNil(CompanionJSONValue.int(1).stringValue)
        XCTAssertNil(CompanionJSONValue.null.stringValue)
        XCTAssertNil(CompanionJSONValue.bool(true).stringValue)
        XCTAssertNil(CompanionJSONValue.array([]).stringValue)
        XCTAssertNil(CompanionJSONValue.object([:]).stringValue)
    }

    // MARK: - CompanionMessage.plainText

    func testPlainTextOfTextContent() {
        let msg = makeMessage(content: .text("just text"))
        XCTAssertEqual(msg.plainText, "just text")
    }

    func testPlainTextOfBlocksContent() {
        let blocks: [[String: CompanionJSONValue]] = [
            ["type": .string("text"), "text": .string("hello ")],
            ["type": .string("text"), "text": .string("world")],
            ["type": .string("citation"), "id": .string("c1")] // no "text" key
        ]
        let msg = makeMessage(content: .blocks(blocks))
        XCTAssertEqual(msg.plainText, "hello world")
    }

    func testPlainTextOfEmptyBlocks() {
        let msg = makeMessage(content: .blocks([]))
        XCTAssertEqual(msg.plainText, "")
    }

    // MARK: - CompanionCitation

    func testCitationDecodesFromSnakeCase() throws {
        let json = """
        {"id":"cit-1","segment_id":"seg-1","recording_id":"rec-1","span_start":10,"span_end":20,"citation_index":3}
        """.data(using: .utf8)!
        let citation = try decoder.decode(CompanionCitation.self, from: json)
        XCTAssertEqual(citation.id, "cit-1")
        XCTAssertEqual(citation.segmentId, "seg-1")
        XCTAssertEqual(citation.recordingId, "rec-1")
        XCTAssertEqual(citation.spanStart, 10)
        XCTAssertEqual(citation.spanEnd, 20)
        XCTAssertEqual(citation.citationIndex, 3)
    }

    func testCitationOptionalFieldsCanBeNull() throws {
        let json = """
        {"id":"cit-1","segment_id":null,"recording_id":null,"span_start":0,"span_end":5,"citation_index":0}
        """.data(using: .utf8)!
        let citation = try decoder.decode(CompanionCitation.self, from: json)
        XCTAssertNil(citation.segmentId)
        XCTAssertNil(citation.recordingId)
    }

    // MARK: - CompanionConversation

    func testConversationDecodes() throws {
        let json = """
        {"id":"conv-1","title":"Discussion","scope":null,"pinned_at":null,
         "last_message_at":"2026-05-18T10:00:00Z","archived_at":null,
         "created_at":"2026-05-18T09:00:00Z","updated_at":"2026-05-18T10:00:00Z"}
        """.data(using: .utf8)!
        let convo = try decoder.decode(CompanionConversation.self, from: json)
        XCTAssertEqual(convo.id, "conv-1")
        XCTAssertEqual(convo.title, "Discussion")
        XCTAssertNil(convo.pinnedAt)
        XCTAssertNil(convo.archivedAt)
        XCTAssertNotNil(convo.lastMessageAt)
    }

    // MARK: - CompanionConversationList

    func testConversationListDecodes() throws {
        let json = """
        {"chats": [
            {"id":"c1","title":"a","scope":null,"pinned_at":null,
             "last_message_at":null,"archived_at":null,
             "created_at":"2026-05-18T09:00:00Z","updated_at":"2026-05-18T09:00:00Z"},
            {"id":"c2","title":null,"scope":null,"pinned_at":null,
             "last_message_at":null,"archived_at":null,
             "created_at":"2026-05-18T09:00:00Z","updated_at":"2026-05-18T09:00:00Z"}
        ]}
        """.data(using: .utf8)!
        let list = try decoder.decode(CompanionConversationList.self, from: json)
        XCTAssertEqual(list.chats.count, 2)
        XCTAssertEqual(list.chats[0].id, "c1")
        XCTAssertNil(list.chats[1].title)
    }

    // MARK: - CompanionStreamEvent

    func testStreamEventCases() {
        let citation = CompanionStreamCitation(
            index: 1, segmentId: "s1", recordingId: "r1",
            startMs: 100, endMs: 200, spanStart: 0, spanEnd: 5
        )
        let events: [CompanionStreamEvent] = [
            .turnStart(messageId: "m1", conversationId: "c1"),
            .toolCall(callId: "t1", tool: "search"),
            .toolResult(callId: "t1", summary: "ok"),
            .token(text: "hi"),
            .citation(citation),
            .done(messageId: "m1", model: "gpt", latencyMs: 250),
            .error(code: "rate_limit", message: "too many")
        ]

        // Pairwise equality across the same event values; pairwise inequality between
        // the same-case events with different payloads.
        XCTAssertEqual(events[0], CompanionStreamEvent.turnStart(messageId: "m1", conversationId: "c1"))
        XCTAssertNotEqual(events[0], CompanionStreamEvent.turnStart(messageId: "m2", conversationId: "c1"))
        XCTAssertNotEqual(events[3], CompanionStreamEvent.token(text: "bye"))
    }

    // MARK: - Helpers

    private func makeMessage(content: CompanionContent) -> CompanionMessage {
        // Building via JSON since CompanionMessage's `init` is synthesized
        // and not exposed (no public memberwise init).
        let blocks: String
        switch content {
        case .text(let s):
            blocks = "\"\(s.replacingOccurrences(of: "\"", with: "\\\""))\""
        case .blocks(let b):
            // Hand-serialise to JSON
            let data = try! JSONEncoder().encode(b)
            blocks = String(data: data, encoding: .utf8)!
        }
        let json = """
        {"id":"msg-1","role":"assistant","content":\(blocks),"tool_calls":null,
         "citations":[],"model":"gpt","input_tokens":1,"output_tokens":2,
         "cached_tokens":0,"latency_ms":10,"created_at":"2026-05-18T10:00:00Z"}
        """.data(using: .utf8)!
        return try! decoder.decode(CompanionMessage.self, from: json)
    }
}
