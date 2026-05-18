import Foundation

/// Parses a stream of bytes into typed `CompanionStreamEvent` values.
///
/// Frames are separated by `\n\n`. Each frame is `event: <type>\ndata: <json>`.
public struct CompanionStreamParser: Sendable {
    public init() {}

    public func parse(_ frame: String) -> CompanionStreamEvent? {
        var eventType: String?
        var dataLine: String?
        for rawLine in frame.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(rawLine)
            if line.hasPrefix("event: ") {
                eventType = String(line.dropFirst("event: ".count))
                    .trimmingCharacters(in: .whitespaces)
            } else if line.hasPrefix("data: ") {
                dataLine = String(line.dropFirst("data: ".count))
            }
        }
        guard let eventType, let dataLine, let data = dataLine.data(using: .utf8) else {
            return nil
        }
        let decoder = JSONDecoder()
        switch eventType {
        case "turn_start":
            let payload = try? decoder.decode(TurnStartPayload.self, from: data)
            return payload.map {
                .turnStart(messageId: $0.messageId, conversationId: $0.conversationId)
            }
        case "tool_call":
            let payload = try? decoder.decode(ToolCallPayload.self, from: data)
            return payload.map { .toolCall(callId: $0.callId, tool: $0.tool) }
        case "tool_result":
            let payload = try? decoder.decode(ToolResultPayload.self, from: data)
            return payload.map { .toolResult(callId: $0.callId, summary: $0.summary) }
        case "token":
            let payload = try? decoder.decode(TokenPayload.self, from: data)
            return payload.map { .token(text: $0.text) }
        case "citation":
            let payload = try? decoder.decode(CitationPayload.self, from: data)
            return payload.map {
                .citation(
                    CompanionStreamCitation(
                        index: $0.index,
                        segmentId: $0.segmentId,
                        recordingId: $0.recordingId,
                        startMs: $0.startMs,
                        endMs: $0.endMs,
                        spanStart: $0.spanStart,
                        spanEnd: $0.spanEnd
                    )
                )
            }
        case "done":
            let payload = try? decoder.decode(DonePayload.self, from: data)
            return payload.map {
                .done(messageId: $0.messageId, model: $0.model, latencyMs: $0.latencyMs)
            }
        case "error":
            let payload = try? decoder.decode(ErrorPayload.self, from: data)
            return payload.map { .error(code: $0.code, message: $0.message) }
        default:
            return nil
        }
    }

    // MARK: - Payloads

    private struct TurnStartPayload: Decodable {
        let messageId: String
        let conversationId: String
        enum CodingKeys: String, CodingKey {
            case messageId = "message_id"
            case conversationId = "conversation_id"
        }
    }

    private struct ToolCallPayload: Decodable {
        let callId: String
        let tool: String
        enum CodingKeys: String, CodingKey {
            case callId = "call_id"
            case tool
        }
    }

    private struct ToolResultPayload: Decodable {
        let callId: String
        let summary: String
        enum CodingKeys: String, CodingKey {
            case callId = "call_id"
            case summary
        }
    }

    private struct TokenPayload: Decodable {
        let text: String
    }

    private struct CitationPayload: Decodable {
        let index: Int
        let segmentId: String
        let recordingId: String
        let startMs: Int?
        let endMs: Int?
        let spanStart: Int
        let spanEnd: Int
        enum CodingKeys: String, CodingKey {
            case index
            case segmentId = "segment_id"
            case recordingId = "recording_id"
            case startMs = "start_ms"
            case endMs = "end_ms"
            case spanStart = "span_start"
            case spanEnd = "span_end"
        }
    }

    private struct DonePayload: Decodable {
        let messageId: String
        let model: String
        let latencyMs: Int
        enum CodingKeys: String, CodingKey {
            case messageId = "message_id"
            case model
            case latencyMs = "latency_ms"
        }
    }

    private struct ErrorPayload: Decodable {
        let code: String
        let message: String
    }
}

/// Consumes a byte stream from the Companion SSE endpoint and yields typed
/// events.  Splits chunks on `\n\n` boundaries; trailing whitespace at EOF is
/// flushed as a final frame when present.
public func companionEvents<S: AsyncSequence>(
    bytes: S,
    parser: CompanionStreamParser = CompanionStreamParser()
) -> AsyncStream<CompanionStreamEvent> where S.Element == UInt8 {
    AsyncStream { continuation in
        let task = Task {
            var buffer = ""
            do {
                for try await byte in bytes {
                    buffer.append(Character(UnicodeScalar(byte)))
                    while let range = buffer.range(of: "\n\n") {
                        let frame = String(buffer[buffer.startIndex..<range.lowerBound])
                        buffer = String(buffer[range.upperBound...])
                        if let event = parser.parse(frame) {
                            continuation.yield(event)
                        }
                    }
                }
                let trailing = buffer.trimmingCharacters(in: .whitespacesAndNewlines)
                if !trailing.isEmpty, let event = parser.parse(trailing) {
                    continuation.yield(event)
                }
            } catch {
                continuation.yield(.error(code: "stream_error", message: error.localizedDescription))
            }
            continuation.finish()
        }
        continuation.onTermination = { _ in task.cancel() }
    }
}
