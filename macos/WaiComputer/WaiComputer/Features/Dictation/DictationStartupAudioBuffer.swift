import Foundation
import WaiComputerKit

actor DictationStartupAudioBuffer {
    enum AppendResult: Equatable {
        case buffered(chunks: Int, bytes: Int)
        case sent(bytes: Int)
    }

    enum FlushResult: Equatable {
        case flushed(chunks: Int, bytes: Int)

        var chunks: Int {
            switch self {
            case .flushed(let chunks, _): return chunks
            }
        }

        var bytes: Int {
            switch self {
            case .flushed(_, let bytes): return bytes
            }
        }
    }

    private let maxBufferedBytes: Int
    private var bufferedChunks: [Data] = []
    private var bufferedBytes = 0
    private var provider: (any ProviderSession)?
    private var isFlushing = false

    init(maxBufferedBytes: Int) {
        self.maxBufferedBytes = max(1, maxBufferedBytes)
    }

    func append(_ data: Data) async throws -> AppendResult {
        guard !data.isEmpty else {
            return .buffered(chunks: bufferedChunks.count, bytes: bufferedBytes)
        }

        if let provider, !isFlushing {
            try await provider.send(pcm16: data)
            return .sent(bytes: data.count)
        }

        let nextBufferedBytes = bufferedBytes + data.count
        guard nextBufferedBytes <= maxBufferedBytes else {
            throw DictationStartupAudioBufferError.capacityExceeded(
                bytes: nextBufferedBytes,
                limit: maxBufferedBytes
            )
        }

        bufferedChunks.append(data)
        bufferedBytes = nextBufferedBytes
        return .buffered(chunks: bufferedChunks.count, bytes: bufferedBytes)
    }

    func startStreaming(to provider: any ProviderSession) async throws -> FlushResult {
        isFlushing = true
        var sentBytes = 0
        var sentChunks = 0

        do {
            while !bufferedChunks.isEmpty {
                let chunks = bufferedChunks
                bufferedChunks = []
                bufferedBytes = 0

                for chunk in chunks {
                    try await provider.send(pcm16: chunk)
                    sentBytes += chunk.count
                    sentChunks += 1
                }
            }
        } catch {
            isFlushing = false
            self.provider = nil
            throw error
        }

        self.provider = provider
        isFlushing = false
        return .flushed(chunks: sentChunks, bytes: sentBytes)
    }

    func close() {
        provider = nil
        isFlushing = false
        bufferedChunks = []
        bufferedBytes = 0
    }
}

enum DictationStartupAudioBufferError: Error, LocalizedError, Equatable {
    case capacityExceeded(bytes: Int, limit: Int)

    var errorDescription: String? {
        switch self {
        case .capacityExceeded(let bytes, let limit):
            return "Dictation startup audio buffer exceeded \(limit) bytes (received \(bytes))."
        }
    }
}
