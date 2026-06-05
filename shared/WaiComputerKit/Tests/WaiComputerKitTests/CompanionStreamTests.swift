import XCTest
@testable import WaiComputerKit

final class CompanionStreamTests: XCTestCase {

    private let parser = CompanionStreamParser()

    func testParsesTurnStartFrame() throws {
        let frame = """
        event: turn_start
        data: {"message_id":"m1","conversation_id":"c1"}
        """
        let event = try parser.parse(frame)
        XCTAssertEqual(event, .turnStart(messageId: "m1", conversationId: "c1"))
    }

    func testParsesToolCallAndResultFrames() throws {
        let call = try parser.parse("event: tool_call\ndata: {\"call_id\":\"t1\",\"tool\":\"search_transcripts\",\"args\":{\"query\":\"x\"}}")
        XCTAssertEqual(call, .toolCall(callId: "t1", tool: "search_transcripts"))

        let result = try parser.parse("event: tool_result\ndata: {\"call_id\":\"t1\",\"summary\":\"3 segments\"}")
        XCTAssertEqual(result, .toolResult(callId: "t1", summary: "3 segments", ok: true))
    }

    func testParsesThinkingAndPlanFrames() throws {
        let thinking = try parser.parse("event: thinking\ndata: {\"text\":\"Let me check.\"}")
        XCTAssertEqual(thinking, .thinking(text: "Let me check."))

        let plan = try parser.parse(
            "event: plan\ndata: {\"steps\":[{\"title\":\"Search\",\"status\":\"in_progress\"},"
            + "{\"title\":\"Summarize\",\"status\":\"pending\"}]}"
        )
        XCTAssertEqual(plan, .plan(steps: [
            CompanionPlanStep(title: "Search", status: "in_progress"),
            CompanionPlanStep(title: "Summarize", status: "pending"),
        ]))
    }

    func testParsesArtifactFrame() throws {
        let event = try parser.parse(
            "event: artifact\ndata: {\"artifact_id\":\"a1\",\"title\":\"Landing\","
            + "\"kind\":\"html\",\"content\":\"<h1>Hi</h1>\",\"language\":\"\"}"
        )
        guard case .artifact(let artifact) = event else {
            return XCTFail("expected artifact event, got \(String(describing: event))")
        }
        XCTAssertEqual(artifact.artifactId, "a1")
        XCTAssertEqual(artifact.title, "Landing")
        XCTAssertEqual(artifact.kind, "html")
        XCTAssertEqual(artifact.content, "<h1>Hi</h1>")
    }

    func testParsesWebCitationsFrame() throws {
        let event = try parser.parse(
            "event: web_citations\ndata: {\"citations\":[{\"title\":\"Runpod\","
            + "\"url\":\"https://www.runpod.io/serverless-gpu\","
            + "\"start_index\":4,\"end_index\":10}]}"
        )
        guard case .webCitations(let citations) = event else {
            return XCTFail("expected web citations event, got \(String(describing: event))")
        }
        XCTAssertEqual(citations, [
            CompanionWebCitation(
                title: "Runpod",
                url: "https://www.runpod.io/serverless-gpu",
                startIndex: 4,
                endIndex: 10
            ),
        ])
    }

    func testToolResultDefaultsOkTrueAndParsesOkFalse() throws {
        let okMissing = try parser.parse("event: tool_result\ndata: {\"call_id\":\"t1\",\"summary\":\"Done\"}")
        XCTAssertEqual(okMissing, .toolResult(callId: "t1", summary: "Done", ok: true))
        let failed = try parser.parse(
            "event: tool_result\ndata: {\"call_id\":\"t1\",\"summary\":\"Failed\",\"ok\":false}"
        )
        XCTAssertEqual(failed, .toolResult(callId: "t1", summary: "Failed", ok: false))
    }

    func testParsesTokenFrame() throws {
        let event = try parser.parse("event: token\ndata: {\"text\":\"hello\"}")
        XCTAssertEqual(event, .token(text: "hello"))
    }

    func testParsesCitationFrame() throws {
        let event = try parser.parse("""
        event: citation
        data: {"index":1,"segment_id":"s1","recording_id":"r1","start_ms":1000,"end_ms":2000,"span_start":0,"span_end":5}
        """)
        guard case .citation(let cit) = event else {
            XCTFail("Expected citation event, got \(String(describing: event))")
            return
        }
        XCTAssertEqual(cit.index, 1)
        XCTAssertEqual(cit.segmentId, "s1")
        XCTAssertEqual(cit.recordingId, "r1")
        XCTAssertEqual(cit.startMs, 1000)
        XCTAssertEqual(cit.endMs, 2000)
    }

    func testParsesDoneAndErrorFrames() throws {
        let done = try parser.parse("event: done\ndata: {\"message_id\":\"a1\",\"model\":\"gpt-5.5\",\"latency_ms\":1234}")
        XCTAssertEqual(done, .done(messageId: "a1", model: "gpt-5.5", latencyMs: 1234))

        let err = try parser.parse("event: error\ndata: {\"code\":\"boom\",\"message\":\"bad\"}")
        XCTAssertEqual(err, .error(code: "boom", message: "bad"))
    }

    func testCommentOnlyFrameYieldsNil() throws {
        XCTAssertNil(try parser.parse(": keep-alive"))
    }

    func testThrowsOnMalformedFrames() {
        XCTAssertThrowsError(try parser.parse("event: token\nno data line"))
        XCTAssertThrowsError(try parser.parse("event: token\ndata: not valid json"))
        XCTAssertThrowsError(try parser.parse("data: orphan"))
    }

    func testOptionalLeadingSpaceAfterColon() throws {
        let frame = "event:token\ndata:{\"text\":\"compact\"}"
        let event = try parser.parse(frame)
        XCTAssertEqual(event, .token(text: "compact"))
    }

    func testStreamingByteSequenceYieldsEventsInOrder() async {
        let raw = """
        event: turn_start
        data: {"message_id":"m1","conversation_id":"c1"}

        event: token
        data: {"text":"hi"}

        event: done
        data: {"message_id":"a1","model":"gpt-5.5","latency_ms":42}


        """
        let bytes = AsyncByteSequence(string: raw)
        var collected: [CompanionStreamEvent] = []
        for await event in companionEvents(bytes: bytes) {
            collected.append(event)
        }
        XCTAssertEqual(collected.count, 3)
        XCTAssertEqual(collected[0], .turnStart(messageId: "m1", conversationId: "c1"))
        XCTAssertEqual(collected[1], .token(text: "hi"))
        XCTAssertEqual(collected[2], .done(messageId: "a1", model: "gpt-5.5", latencyMs: 42))
    }

    func testStreamingPreservesMultiByteUTF8() async {
        let payload = "Привет 🌊 мир"
        let raw = """
        event: token
        data: {"text":"\(payload)"}


        """
        let bytes = AsyncByteSequence(string: raw)
        var collected: [CompanionStreamEvent] = []
        for await event in companionEvents(bytes: bytes) {
            collected.append(event)
        }
        XCTAssertEqual(collected, [.token(text: payload)])
    }

    func testStreamingReassemblesFramesSplitAcrossChunks() async {
        let raw = """
        event: token
        data: {"text":"Привет"}

        event: done
        data: {"message_id":"a1","model":"gpt-5.5","latency_ms":1}


        """
        let allBytes = Array(raw.utf8)
        let chunked = AsyncByteSequence(bytes: allBytes)
        var collected: [CompanionStreamEvent] = []
        for await event in companionEvents(bytes: chunked) {
            collected.append(event)
        }
        XCTAssertEqual(collected.count, 2)
        XCTAssertEqual(collected[0], .token(text: "Привет"))
        XCTAssertEqual(collected[1], .done(messageId: "a1", model: "gpt-5.5", latencyMs: 1))
    }

    func testStreamingSkipsHeartbeatComments() async {
        let raw = """
        : keep-alive

        event: token
        data: {"text":"hi"}

        : another heartbeat


        """
        let bytes = AsyncByteSequence(string: raw)
        var collected: [CompanionStreamEvent] = []
        for await event in companionEvents(bytes: bytes) {
            collected.append(event)
        }
        XCTAssertEqual(collected, [.token(text: "hi")])
    }

    func testStreamingYieldsParseErrorOnMalformedPayload() async {
        let raw = """
        event: token
        data: not-json


        """
        let bytes = AsyncByteSequence(string: raw)
        var collected: [CompanionStreamEvent] = []
        for await event in companionEvents(bytes: bytes) {
            collected.append(event)
        }
        XCTAssertEqual(collected.count, 1)
        guard case .error(let code, _) = collected[0] else {
            XCTFail("Expected error event, got \(collected[0])")
            return
        }
        XCTAssertEqual(code, "parse_error")
    }
}

/// Minimal byte-emitting async sequence used to drive companionEvents().
private struct AsyncByteSequence: AsyncSequence {
    typealias Element = UInt8
    let bytes: [UInt8]

    init(string: String) {
        self.bytes = Array(string.utf8)
    }

    init(bytes: [UInt8]) {
        self.bytes = bytes
    }

    func makeAsyncIterator() -> Iterator {
        Iterator(bytes: bytes)
    }

    struct Iterator: AsyncIteratorProtocol {
        var bytes: [UInt8]
        var index = 0

        mutating func next() async -> UInt8? {
            guard index < bytes.count else { return nil }
            defer { index += 1 }
            return bytes[index]
        }
    }
}
