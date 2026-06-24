import AVFoundation
import XCTest
@testable import WaiComputerKit

private actor DictationCommitGate {
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
        let waiters = waiters
        self.waiters = []
        waiters.forEach { $0.resume() }
    }
}

private actor SlowOpeningDictationProvider: ProviderSession {
    nonisolated let events: AsyncStream<TranscriptionEvent>
    nonisolated let openStarted: AsyncStream<Void>

    private let eventContinuation: AsyncStream<TranscriptionEvent>.Continuation
    private var openStartedContinuation: AsyncStream<Void>.Continuation?
    private let gate: DictationCommitGate
    private let finalSegment: LiveTranscriptSegment
    private var didClose = false

    init(gate: DictationCommitGate, finalSegment: LiveTranscriptSegment) {
        self.gate = gate
        self.finalSegment = finalSegment

        let events = AsyncStream.makeStream(of: TranscriptionEvent.self)
        self.events = events.stream
        self.eventContinuation = events.continuation

        let openStarted = AsyncStream.makeStream(of: Void.self)
        self.openStarted = openStarted.stream
        self.openStartedContinuation = openStarted.continuation
    }

    func open() async throws {
        openStartedContinuation?.yield()
        await gate.wait()
    }

    func send(pcm16: Data) async throws {}

    func endTurn() async throws {
        eventContinuation.yield(.committed(finalSegment))
    }

    func close(timeout: Duration) async throws -> [LiveTranscriptSegment] {
        didClose = true
        eventContinuation.finish()
        return [finalSegment]
    }

    func cancel() async {
        eventContinuation.finish()
    }

    func wasClosed() -> Bool {
        didClose
    }
}

final class DictationSessionCommitTests: XCTestCase {
    func testCommitDuringArmingReturnsDeferredCommitOutcome() async throws {
        let gate = DictationCommitGate()
        let finalSegment = LiveTranscriptSegment(
            text: "fast release still transcribes",
            speaker: nil,
            isFinal: true,
            startMs: 0,
            endMs: 1_000,
            confidence: 0.95
        )
        let provider = SlowOpeningDictationProvider(gate: gate, finalSegment: finalSegment)
        let session = try makeSession(provider: provider)

        let armTask = Task {
            try await session.arm()
        }

        var openStarted = provider.openStarted.makeAsyncIterator()
        _ = await openStarted.next()

        let commitTask = Task {
            try await session.commit(timeout: .seconds(1))
        }

        try await Task.sleep(for: .milliseconds(50))
        await gate.open()

        try await armTask.value
        let outcome = try await commitTask.value

        XCTAssertEqual(outcome.transcript, "fast release still transcribes")
        XCTAssertEqual(outcome.segments.map(\.text), ["fast release still transcribes"])
        let providerWasClosed = await provider.wasClosed()
        XCTAssertTrue(providerWasClosed)
    }

    private func makeSession(provider: any ProviderSession) throws -> DictationSession {
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        continuation.finish()
        let format = try XCTUnwrap(AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 16_000,
            channels: 1,
            interleaved: false
        ))
        let lease = AudioEngineHost.Lease(
            id: UUID(),
            preRoll: [],
            buffers: stream,
            nativeInputFormat: format,
            outputFormat: format
        )
        return DictationSession(provider: provider, lease: lease, host: AudioEngineHost.shared)
    }
}
