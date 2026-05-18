import Foundation

/// Errors raised while consuming the Companion SSE stream.
public enum CompanionStreamError: Error, LocalizedError, Sendable {
    case malformedFrame(String)
    case malformedPayload(eventType: String, underlying: Error)
    case unknownEventType(String)

    public var errorDescription: String? {
        switch self {
        case .malformedFrame(let detail):
            return "Malformed SSE frame: \(detail)"
        case .malformedPayload(let eventType, let underlying):
            return "Failed to decode \(eventType) payload: \(underlying.localizedDescription)"
        case .unknownEventType(let name):
            return "Unknown SSE event type: \(name)"
        }
    }
}

/// Parses a stream of bytes into typed `CompanionStreamEvent` values.
///
/// Frames are separated by `\n\n`. Each frame is `event: <type>\ndata: <json>`.
/// Per the SSE spec, multiple `data:` lines in one frame are joined with `\n`,
/// lines beginning with `:` are comments (heartbeats), and decoding errors
/// are surfaced as `CompanionStreamError` rather than silently dropped.
public struct CompanionStreamParser: Sendable {
    public init() {}

    /// Parse one complete SSE frame. Returns `nil` only when the frame is a
    /// comment/heartbeat with no real event. Throws on malformed payloads.
    public func parse(_ frame: String) throws -> CompanionStreamEvent? {
        var eventType: String?
        var dataLines: [String] = []
        var sawContentLine = false
        for rawLine in frame.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(rawLine)
            if line.isEmpty { continue }
            if line.hasPrefix(":") {
                continue
            }
            sawContentLine = true
            if let value = fieldValue(in: line, prefix: "event:") {
                eventType = value.trimmingCharacters(in: .whitespaces)
            } else if let value = fieldValue(in: line, prefix: "data:") {
                dataLines.append(value)
            } else if fieldValue(in: line, prefix: "id:") != nil
                || fieldValue(in: line, prefix: "retry:") != nil {
                continue
            } else {
                throw CompanionStreamError.malformedFrame(
                    "Unrecognized line: \(line)"
                )
            }
        }
        if !sawContentLine {
            return nil
        }
        guard let eventType else {
            throw CompanionStreamError.malformedFrame("Frame missing event: field")
        }
        if dataLines.isEmpty {
            throw CompanionStreamError.malformedFrame(
                "Frame for event '\(eventType)' has no data: line"
            )
        }
        let dataString = dataLines.joined(separator: "\n")
        guard let data = dataString.data(using: .utf8) else {
            throw CompanionStreamError.malformedFrame(
                "Frame data is not valid UTF-8"
            )
        }
        let decoder = JSONDecoder()
        do {
            switch eventType {
            case "turn_start":
                let payload = try decoder.decode(TurnStartPayload.self, from: data)
                return .turnStart(
                    messageId: payload.messageId,
                    conversationId: payload.conversationId
                )
            case "tool_call":
                let payload = try decoder.decode(ToolCallPayload.self, from: data)
                return .toolCall(callId: payload.callId, tool: payload.tool)
            case "tool_result":
                let payload = try decoder.decode(ToolResultPayload.self, from: data)
                return .toolResult(callId: payload.callId, summary: payload.summary)
            case "token":
                let payload = try decoder.decode(TokenPayload.self, from: data)
                return .token(text: payload.text)
            case "citation":
                let payload = try decoder.decode(CitationPayload.self, from: data)
                return .citation(
                    CompanionStreamCitation(
                        index: payload.index,
                        segmentId: payload.segmentId,
                        recordingId: payload.recordingId,
                        startMs: payload.startMs,
                        endMs: payload.endMs,
                        spanStart: payload.spanStart,
                        spanEnd: payload.spanEnd
                    )
                )
            case "done":
                let payload = try decoder.decode(DonePayload.self, from: data)
                return .done(
                    messageId: payload.messageId,
                    model: payload.model,
                    latencyMs: payload.latencyMs
                )
            case "error":
                let payload = try decoder.decode(ErrorPayload.self, from: data)
                return .error(code: payload.code, message: payload.message)
            default:
                throw CompanionStreamError.unknownEventType(eventType)
            }
        } catch let error as CompanionStreamError {
            throw error
        } catch {
            throw CompanionStreamError.malformedPayload(
                eventType: eventType,
                underlying: error
            )
        }
    }

    private func fieldValue(in line: String, prefix: String) -> String? {
        guard line.hasPrefix(prefix) else { return nil }
        var value = line.dropFirst(prefix.count)
        if value.first == " " {
            value = value.dropFirst()
        }
        return String(value)
    }

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
/// events. Buffers raw bytes (so multi-byte UTF-8 characters are never split
/// across `Character` boundaries) and slices on `\n\n` frame terminators.
/// Cancellation of the underlying iterator closes silently; parse failures
/// surface as `.error` events with `code: "parse_error"`.
public func companionEvents<S: AsyncSequence>(
    bytes: S,
    parser: CompanionStreamParser = CompanionStreamParser()
) -> AsyncStream<CompanionStreamEvent> where S.Element == UInt8 {
    AsyncStream { continuation in
        let task = Task {
            var buffer = Data()
            do {
                for try await byte in bytes {
                    if Task.isCancelled { break }
                    buffer.append(byte)
                    while let range = buffer.firstFrameTerminator() {
                        let frameBytes = buffer.subdata(in: 0..<range.lowerBound)
                        buffer.removeSubrange(0..<range.upperBound)
                        if let event = try decodeFrame(frameBytes, parser: parser) {
                            continuation.yield(event)
                        }
                    }
                }
                if !buffer.isEmpty {
                    if let event = try decodeFrame(buffer, parser: parser) {
                        continuation.yield(event)
                    }
                }
            } catch is CancellationError {
                // Caller cancelled; close silently.
            } catch let urlError as URLError where urlError.code == .cancelled {
                // Underlying URLSession task cancellation; close silently.
            } catch let parseError as CompanionStreamError {
                continuation.yield(
                    .error(
                        code: "parse_error",
                        message: parseError.errorDescription ?? "Malformed SSE frame"
                    )
                )
            } catch {
                continuation.yield(
                    .error(
                        code: "stream_error",
                        message: error.localizedDescription
                    )
                )
            }
            continuation.finish()
        }
        continuation.onTermination = { _ in task.cancel() }
    }
}

private func decodeFrame(
    _ bytes: Data,
    parser: CompanionStreamParser
) throws -> CompanionStreamEvent? {
    guard !bytes.isEmpty else { return nil }
    guard let frame = String(data: bytes, encoding: .utf8) else {
        throw CompanionStreamError.malformedFrame(
            "Frame is not valid UTF-8 (\(bytes.count) bytes)"
        )
    }
    return try parser.parse(frame)
}

private extension Data {
    /// Find the byte range of the first `\n\n` (frame terminator). Tolerates
    /// `\r\n\r\n` from servers that emit CRLF too.
    func firstFrameTerminator() -> Range<Int>? {
        let bytes = [UInt8](self)
        guard bytes.count >= 2 else { return nil }
        var i = 0
        while i < bytes.count - 1 {
            if bytes[i] == 0x0A && bytes[i + 1] == 0x0A {
                return i..<(i + 2)
            }
            if i + 3 < bytes.count
                && bytes[i] == 0x0D
                && bytes[i + 1] == 0x0A
                && bytes[i + 2] == 0x0D
                && bytes[i + 3] == 0x0A {
                return i..<(i + 4)
            }
            i += 1
        }
        return nil
    }
}
