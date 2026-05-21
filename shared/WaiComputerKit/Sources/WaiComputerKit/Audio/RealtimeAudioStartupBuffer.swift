import Foundation

/// Buffers local PCM captured while a realtime provider session is still
/// opening, then flushes it in order once the socket is ready.
public actor RealtimeAudioStartupBuffer {
    private var chunks: [Data] = []
    private var bytes = 0
    private var connected = false
    private var flushing = false
    private let maxBufferedBytes: Int

    public init(maxBufferedBytes: Int = 480_000) {
        self.maxBufferedBytes = max(1, maxBufferedBytes)
    }

    public var bufferedBytes: Int { bytes }

    public func append(
        _ data: Data,
        send: @Sendable (Data) async throws -> Void
    ) async throws {
        guard !data.isEmpty else { return }
        if connected && !flushing {
            try await send(data)
            return
        }

        chunks.append(data)
        bytes += data.count
        trimToCapacity()
    }

    public func connectAndFlush(
        send: @Sendable (Data) async throws -> Void
    ) async throws {
        guard !connected else { return }
        flushing = true
        defer {
            if !connected {
                flushing = false
            }
        }
        while !chunks.isEmpty {
            let chunk = chunks[0]
            try await send(chunk)
            chunks.removeFirst()
            bytes -= chunk.count
        }
        connected = true
        flushing = false
    }

    private func trimToCapacity() {
        while bytes > maxBufferedBytes, !chunks.isEmpty {
            bytes -= chunks.removeFirst().count
        }
    }
}
