import Foundation

public enum DictationCleanupStreamError: Error, LocalizedError, Sendable {
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

public enum DictationCleanupStreamEvent: Sendable, Equatable {
    case token(text: String)
    case done(
        text: String,
        model: String?,
        latencyMs: Int,
        inputTokens: Int?,
        outputTokens: Int?,
        cachedTokens: Int?
    )
    case error(code: String, message: String)
}

public struct DictationCleanupStreamParser: Sendable {
    public init() {}

    public func parse(_ frame: String) throws -> DictationCleanupStreamEvent? {
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
                throw DictationCleanupStreamError.malformedFrame(
                    "Unrecognized line: \(line)"
                )
            }
        }
        if !sawContentLine {
            return nil
        }
        guard let eventType else {
            throw DictationCleanupStreamError.malformedFrame("Frame missing event: field")
        }
        if dataLines.isEmpty {
            throw DictationCleanupStreamError.malformedFrame(
                "Frame for event '\(eventType)' has no data: line"
            )
        }
        let dataString = dataLines.joined(separator: "\n")
        guard let data = dataString.data(using: .utf8) else {
            throw DictationCleanupStreamError.malformedFrame(
                "Frame data is not valid UTF-8"
            )
        }
        let decoder = JSONDecoder()
        do {
            switch eventType {
            case "token":
                let payload = try decoder.decode(TokenPayload.self, from: data)
                return .token(text: payload.text)
            case "done":
                let payload = try decoder.decode(DonePayload.self, from: data)
                return .done(
                    text: payload.text,
                    model: payload.model,
                    latencyMs: payload.latencyMs,
                    inputTokens: payload.inputTokens,
                    outputTokens: payload.outputTokens,
                    cachedTokens: payload.cachedTokens
                )
            case "error":
                let payload = try decoder.decode(ErrorPayload.self, from: data)
                return .error(code: payload.code, message: payload.message)
            default:
                throw DictationCleanupStreamError.unknownEventType(eventType)
            }
        } catch let error as DictationCleanupStreamError {
            throw error
        } catch {
            throw DictationCleanupStreamError.malformedPayload(
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

    private struct TokenPayload: Decodable {
        let text: String
    }

    private struct DonePayload: Decodable {
        let text: String
        let model: String?
        let latencyMs: Int
        let inputTokens: Int?
        let outputTokens: Int?
        let cachedTokens: Int?

        enum CodingKeys: String, CodingKey {
            case text
            case model
            case latencyMs = "latency_ms"
            case inputTokens = "input_tokens"
            case outputTokens = "output_tokens"
            case cachedTokens = "cached_tokens"
        }
    }

    private struct ErrorPayload: Decodable {
        let code: String
        let message: String
    }
}

public func dictationCleanupEvents<S: AsyncSequence>(
    bytes: S,
    parser: DictationCleanupStreamParser = DictationCleanupStreamParser()
) -> AsyncStream<DictationCleanupStreamEvent> where S.Element == UInt8 {
    AsyncStream { continuation in
        let task = Task {
            var buffer = Data()
            do {
                for try await byte in bytes {
                    if Task.isCancelled { break }
                    buffer.append(byte)
                    while let range = buffer.firstDictationCleanupFrameTerminator() {
                        let frameBytes = buffer.subdata(in: 0..<range.lowerBound)
                        buffer.removeSubrange(0..<range.upperBound)
                        if let event = try decodeDictationCleanupFrame(
                            frameBytes,
                            parser: parser
                        ) {
                            continuation.yield(event)
                        }
                    }
                }
                if !buffer.isEmpty {
                    if let event = try decodeDictationCleanupFrame(buffer, parser: parser) {
                        continuation.yield(event)
                    }
                }
            } catch is CancellationError {
            } catch let urlError as URLError where urlError.code == .cancelled {
            } catch let parseError as DictationCleanupStreamError {
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

private func decodeDictationCleanupFrame(
    _ bytes: Data,
    parser: DictationCleanupStreamParser
) throws -> DictationCleanupStreamEvent? {
    guard !bytes.isEmpty else { return nil }
    guard let frame = String(data: bytes, encoding: .utf8) else {
        throw DictationCleanupStreamError.malformedFrame(
            "Frame is not valid UTF-8 (\(bytes.count) bytes)"
        )
    }
    return try parser.parse(frame)
}

private extension Data {
    func firstDictationCleanupFrameTerminator() -> Range<Int>? {
        let bytes = [UInt8](self)
        guard bytes.count >= 2 else { return nil }
        var index = 0
        while index < bytes.count - 1 {
            if bytes[index] == 0x0A && bytes[index + 1] == 0x0A {
                return index..<(index + 2)
            }
            if index + 3 < bytes.count
                && bytes[index] == 0x0D
                && bytes[index + 1] == 0x0A
                && bytes[index + 2] == 0x0D
                && bytes[index + 3] == 0x0A {
                return index..<(index + 4)
            }
            index += 1
        }
        return nil
    }
}
