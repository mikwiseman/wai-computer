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

private actor DictationCloseGate {
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

private actor BlockingCloseDictationProvider: ProviderSession {
    nonisolated let events: AsyncStream<TranscriptionEvent>
    nonisolated let closeStarted: AsyncStream<Void>

    private let eventContinuation: AsyncStream<TranscriptionEvent>.Continuation
    private let closeStartedContinuation: AsyncStream<Void>.Continuation
    private let gate: DictationCloseGate
    private let finalSegment: LiveTranscriptSegment
    private var sendCount = 0

    init(gate: DictationCloseGate, finalSegment: LiveTranscriptSegment) {
        self.gate = gate
        self.finalSegment = finalSegment

        let events = AsyncStream.makeStream(of: TranscriptionEvent.self)
        self.events = events.stream
        self.eventContinuation = events.continuation

        let closeStarted = AsyncStream.makeStream(of: Void.self)
        self.closeStarted = closeStarted.stream
        self.closeStartedContinuation = closeStarted.continuation
    }

    func open() async throws {}

    func send(pcm16: Data) async throws {
        sendCount += 1
    }

    func endTurn() async throws {
        eventContinuation.yield(.committed(finalSegment))
    }

    func close(timeout: Duration) async throws -> [LiveTranscriptSegment] {
        closeStartedContinuation.yield()
        await gate.wait()
        eventContinuation.finish()
        return [finalSegment]
    }

    func cancel() async {
        eventContinuation.finish()
    }

    func sentChunks() -> Int {
        sendCount
    }
}

private actor ReplacementEventDictationProvider: ProviderSession {
    nonisolated let events: AsyncStream<TranscriptionEvent>

    private let eventContinuation: AsyncStream<TranscriptionEvent>.Continuation

    init() {
        let events = AsyncStream.makeStream(of: TranscriptionEvent.self)
        self.events = events.stream
        self.eventContinuation = events.continuation
    }

    func open() async throws {}

    func send(pcm16: Data) async throws {}

    func endTurn() async throws {
        eventContinuation.yield(.committed(LiveTranscriptSegment(
            text: "hello world",
            speaker: nil,
            isFinal: true,
            startMs: 0,
            endMs: 800,
            confidence: 0.92
        )))
        eventContinuation.yield(.committedReplacement(LiveTranscriptSegment(
            text: "hello world today",
            speaker: nil,
            isFinal: true,
            startMs: 0,
            endMs: 1_200,
            confidence: 0.94
        )))
    }

    func close(timeout: Duration) async throws -> [LiveTranscriptSegment] {
        try? await Task.sleep(for: .milliseconds(50))
        eventContinuation.finish()
        return []
    }

    func cancel() async {
        eventContinuation.finish()
    }
}

private actor FailingSendDictationProvider: ProviderSession {
    nonisolated let events: AsyncStream<TranscriptionEvent>
    nonisolated let sendStarted: AsyncStream<Void>

    private let eventContinuation: AsyncStream<TranscriptionEvent>.Continuation
    private let sendStartedContinuation: AsyncStream<Void>.Continuation
    private var cancelCount = 0

    init() {
        let events = AsyncStream.makeStream(of: TranscriptionEvent.self)
        self.events = events.stream
        self.eventContinuation = events.continuation

        let sendStarted = AsyncStream.makeStream(of: Void.self)
        self.sendStarted = sendStarted.stream
        self.sendStartedContinuation = sendStarted.continuation
    }

    func open() async throws {}

    func send(pcm16: Data) async throws {
        sendStartedContinuation.yield()
        throw ProviderError.transcriberInternal(message: "socket send failed")
    }

    func endTurn() async throws {}

    func close(timeout: Duration) async throws -> [LiveTranscriptSegment] {
        eventContinuation.finish()
        return []
    }

    func cancel() async {
        cancelCount += 1
        eventContinuation.finish()
    }

    func wasCancelled() -> Bool {
        cancelCount > 0
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

    func testCommitUsesReplacementEventWhenCloseReturnsNoSegments() async throws {
        let provider = ReplacementEventDictationProvider()
        let session = try makeSession(provider: provider)

        try await session.arm()
        let outcome = try await session.commit(timeout: .seconds(1))

        XCTAssertEqual(outcome.transcript, "hello world today")
        XCTAssertEqual(outcome.segments.map(\.text), ["hello world today"])
    }

    func testCommitStopsSendingLiveAudioDuringProviderCloseDrain() async throws {
        let gate = DictationCloseGate()
        let finalSegment = LiveTranscriptSegment(
            text: "ready to send",
            speaker: nil,
            isFinal: true,
            startMs: 0,
            endMs: 900,
            confidence: 0.95
        )
        let provider = BlockingCloseDictationProvider(gate: gate, finalSegment: finalSegment)
        let harness = try makeLiveAudioSession(provider: provider)

        try await harness.session.arm()

        _ = harness.continuation.yield(try XCTUnwrap(MockAudioCapture.constantBuffer(
            value: 0.25,
            frameCount: 160
        )))
        try await waitForSentChunks(provider, count: 1)

        let commitTask = Task {
            try await harness.session.commit(timeout: .seconds(1))
        }

        var closeStarted = provider.closeStarted.makeAsyncIterator()
        _ = await closeStarted.next()

        _ = harness.continuation.yield(try XCTUnwrap(MockAudioCapture.constantBuffer(
            value: 0.5,
            frameCount: 160
        )))
        try await Task.sleep(for: .milliseconds(150))

        let chunksAfterFinalizing = await provider.sentChunks()
        XCTAssertEqual(chunksAfterFinalizing, 1)

        await gate.open()
        harness.continuation.finish()

        let outcome = try await commitTask.value
        XCTAssertEqual(outcome.transcript, "ready to send")
    }

    func testAudioSendFailureFailsSessionAndCancelsProvider() async throws {
        let provider = FailingSendDictationProvider()
        let harness = try makeLiveAudioSession(provider: provider)

        try await harness.session.arm()
        var sendStarted = provider.sendStarted.makeAsyncIterator()

        _ = harness.continuation.yield(try XCTUnwrap(MockAudioCapture.constantBuffer(
            value: 0.25,
            frameCount: 160
        )))
        _ = await sendStarted.next()

        let failureMessage = try await waitForFailedPhase(harness.session)
        XCTAssertTrue(failureMessage.contains("provider.send"))
        let providerWasCancelled = await provider.wasCancelled()
        XCTAssertTrue(providerWasCancelled)

        do {
            _ = try await harness.session.commit(timeout: .milliseconds(100))
            XCTFail("commit should throw after an audio send failure")
        } catch {
            XCTAssertTrue(String(describing: error).contains("socket send failed"))
        }

        harness.continuation.finish()
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

    private struct LiveAudioSessionHarness {
        let session: DictationSession
        let continuation: AsyncStream<AVAudioPCMBuffer>.Continuation
    }

    private func makeLiveAudioSession(
        provider: any ProviderSession
    ) throws -> LiveAudioSessionHarness {
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
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
        return LiveAudioSessionHarness(
            session: DictationSession(
                provider: provider,
                lease: lease,
                host: AudioEngineHost.shared
            ),
            continuation: continuation
        )
    }

    private func waitForSentChunks(
        _ provider: BlockingCloseDictationProvider,
        count: Int,
        timeout: Duration = .seconds(1)
    ) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now + timeout
        while clock.now < deadline {
            if await provider.sentChunks() >= count {
                return
            }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("Timed out waiting for \(count) sent chunks")
    }

    private func waitForFailedPhase(
        _ session: DictationSession,
        timeout: Duration = .seconds(1)
    ) async throws -> String {
        let clock = ContinuousClock()
        let deadline = clock.now + timeout
        while clock.now < deadline {
            if case .failed(let message) = await session.phase {
                return message
            }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("Timed out waiting for failed phase")
        return ""
    }
}
