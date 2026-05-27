import Foundation
import XCTest
import WaiComputerKit

private actor RecordingProviderSession: ProviderSession {
    nonisolated let events: AsyncStream<TranscriptionEvent>
    private var payloads: [Data] = []

    init() {
        self.events = AsyncStream { continuation in
            continuation.finish()
        }
    }

    func open() async throws {}

    func send(pcm16: Data) async throws {
        payloads.append(pcm16)
    }

    func endTurn() async throws {}

    func close(timeout: Duration) async throws -> [LiveTranscriptSegment] {
        []
    }

    func cancel() async {}

    func sentPayloads() -> [Data] {
        payloads
    }
}

private actor AsyncGate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }

    func open() {
        isOpen = true
        let continuations = waiters
        waiters = []
        continuations.forEach { $0.resume() }
    }
}

private actor BlockingProviderSession: ProviderSession {
    nonisolated let events: AsyncStream<TranscriptionEvent>
    nonisolated let firstSendStarted: AsyncStream<Void>

    private let gate: AsyncGate
    private var firstSendStartedContinuation: AsyncStream<Void>.Continuation?
    private var payloads: [Data] = []

    init(gate: AsyncGate) {
        self.gate = gate
        self.events = AsyncStream { continuation in
            continuation.finish()
        }

        var firstSendStartedContinuation: AsyncStream<Void>.Continuation?
        self.firstSendStarted = AsyncStream { continuation in
            firstSendStartedContinuation = continuation
        }
        self.firstSendStartedContinuation = firstSendStartedContinuation
    }

    func open() async throws {}

    func send(pcm16: Data) async throws {
        payloads.append(pcm16)
        if payloads.count == 1 {
            firstSendStartedContinuation?.yield()
            await gate.wait()
        }
    }

    func endTurn() async throws {}

    func close(timeout: Duration) async throws -> [LiveTranscriptSegment] {
        []
    }

    func cancel() async {}

    func sentPayloads() -> [Data] {
        payloads
    }
}

final class DictationStartupAudioBufferTests: XCTestCase {
    func testBuffersPCMBeforeProviderOpenThenFlushesInOrder() async throws {
        let buffer = DictationStartupAudioBuffer(maxBufferedBytes: 64)
        let provider = RecordingProviderSession()

        let first = try await buffer.append(Data([0x01]))
        let second = try await buffer.append(Data([0x02, 0x03]))
        let flush = try await buffer.startStreaming(to: provider)
        let live = try await buffer.append(Data([0x04]))
        let sentPayloads = await provider.sentPayloads()

        XCTAssertEqual(first, .buffered(chunks: 1, bytes: 1))
        XCTAssertEqual(second, .buffered(chunks: 2, bytes: 3))
        XCTAssertEqual(flush, .flushed(chunks: 2, bytes: 3))
        XCTAssertEqual(live, .sent(bytes: 1))
        XCTAssertEqual(
            sentPayloads,
            [Data([0x01]), Data([0x02, 0x03]), Data([0x04])]
        )
    }

    func testAppendsDuringFlushStayBehindBufferedStartupAudio() async throws {
        let buffer = DictationStartupAudioBuffer(maxBufferedBytes: 64)
        let gate = AsyncGate()
        let provider = BlockingProviderSession(gate: gate)

        _ = try await buffer.append(Data([0x01]))
        _ = try await buffer.append(Data([0x02]))

        async let flush = buffer.startStreaming(to: provider)
        var firstSendStarted = provider.firstSendStarted.makeAsyncIterator()
        _ = await firstSendStarted.next()

        let appendDuringFlush = Task {
            try await buffer.append(Data([0x09]))
        }
        await Task.yield()
        await gate.open()

        let flushResult = try await flush
        let appendResult = try await appendDuringFlush.value
        let sentPayloads = await provider.sentPayloads()

        XCTAssertEqual(appendResult, .buffered(chunks: 1, bytes: 1))
        XCTAssertEqual(flushResult, .flushed(chunks: 3, bytes: 3))
        XCTAssertEqual(
            sentPayloads,
            [Data([0x01]), Data([0x02]), Data([0x09])]
        )
    }
}
