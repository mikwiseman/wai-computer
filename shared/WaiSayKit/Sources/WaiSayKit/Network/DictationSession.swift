import Foundation
import AVFoundation
import os

private let sessionLog = Logger(subsystem: "com.waisay.kit", category: "dictationSession")

/// Single-source-of-truth orchestrator for one push-to-talk dictation press.
/// Owns the audio lease, the provider session, and the transcript collection.
/// Idempotent via actor isolation — illegal transitions are no-ops, all
/// hotkey-driven mutations serialise through the actor.
///
/// Phase semantics (matches plan):
///   idle → arming → ready → listening → finalizing → done | cancelled | failed
///
/// - `idle`: actor not yet armed, no audio lease, no provider session.
/// - `arming`: leasing the engine + minting a provider session in parallel.
/// - `ready`: provider opened, audio task primed but not yet sending.
/// - `listening`: audio chunks flowing to the provider.
/// - `finalizing`: end-of-turn signalled; draining transcript with a
///   bounded quiet window before close.
/// - `done`: transcript collected, returned to caller.
public actor DictationSession {
    public enum Phase: Sendable, Equatable {
        case idle
        case arming
        case ready
        case listening
        case finalizing
        case done
        case cancelled
        case failed(String)  // String message instead of Error for Equatable
    }

    public struct Outcome: Sendable {
        public let segments: [LiveTranscriptSegment]
        public let transcript: String
        public let language: String?
    }

    public private(set) var phase: Phase = .idle
    public let id = UUID()

    private let provider: InworldProviderSession
    private let lease: AudioEngineHost.Lease
    private weak var hostRef: AudioEngineHost?

    private var audioTask: Task<Void, Never>?
    private var eventTask: Task<Void, Never>?
    private var deferredCommit = false
    private var detectedLanguage: String?
    private var accumulatedSegments: [LiveTranscriptSegment] = []

    /// Construct from an already-acquired audio lease and an unopened
    /// provider session. The session is responsible for closing both
    /// (lease release + provider close) at end-of-life.
    public init(
        provider: InworldProviderSession,
        lease: AudioEngineHost.Lease,
        host: AudioEngineHost
    ) {
        self.provider = provider
        self.lease = lease
        self.hostRef = host
    }

    /// Open the provider WebSocket, send the pre-roll, and begin streaming
    /// live audio. After this returns, the session is in `.listening`.
    public func arm() async throws {
        guard phase == .idle else { return }
        phase = .arming

        do {
            try await provider.open()
        } catch {
            phase = .failed("provider.open: \(error.localizedDescription)")
            throw error
        }

        phase = .ready
        sessionLog.info("[Session \(self.id.uuidString, privacy: .public)] ready")

        startEventLoop()
        startAudioLoop()

        phase = .listening
        if deferredCommit {
            deferredCommit = false
            await commit()
        }
    }

    /// Signal end-of-turn. Drains transcript with a bounded wait, then
    /// returns the assembled outcome.
    public func commit(timeout: Duration = .seconds(3)) async -> Outcome {
        if phase == .arming || phase == .ready {
            // Hotkey released before we even finished connecting. Defer the
            // commit so the listening loop applies it as soon as it transitions.
            deferredCommit = true
            // Wait briefly for arm() to complete.
            for _ in 0..<30 where phase != .listening { try? await Task.sleep(for: .milliseconds(50)) }
        }
        guard phase == .listening else {
            return Outcome(segments: [], transcript: "", language: detectedLanguage)
        }

        phase = .finalizing
        try? await provider.endTurn()

        // The provider's close drains pending frames; meanwhile the event
        // loop kept appending committed segments to `accumulatedSegments`.
        // Take whichever is bigger — defensive against close racing the
        // last `committed` event.
        let drained = (try? await provider.close(timeout: timeout)) ?? []
        let segments = drained.count >= accumulatedSegments.count ? drained : accumulatedSegments
        let transcript = segments.map(\.text).filter { !$0.isEmpty }.joined(separator: " ")

        eventTask?.cancel()
        audioTask?.cancel()
        await releaseLeaseIfNeeded()

        phase = .done
        return Outcome(segments: segments, transcript: transcript, language: detectedLanguage)
    }

    /// Cancel without producing a transcript. Idempotent.
    public func cancel() async {
        if case .failed = phase { return }
        if phase == .done || phase == .cancelled { return }
        phase = .cancelled
        await provider.cancel()
        eventTask?.cancel()
        audioTask?.cancel()
        await releaseLeaseIfNeeded()
    }

    // MARK: - Private

    private func startEventLoop() {
        let stream = provider.events
        eventTask = Task { [weak self] in
            for await event in stream {
                guard let self else { return }
                if Task.isCancelled { return }
                await self.handle(event: event)
            }
        }
    }

    private func handle(event: TranscriptionEvent) {
        switch event {
        case .interim(_, let lang):
            if let lang { detectedLanguage = lang }
        case .committed(let segment):
            accumulatedSegments.append(segment)
        case .providerWarning(let err):
            sessionLog.warning("[Session \(self.id.uuidString, privacy: .public)] provider warning fingerprint=\(err.fingerprint, privacy: .public)")
        case .closed(let reason):
            if case .serverError = reason {
                phase = .failed("provider.closed.serverError")
                audioTask?.cancel()
            }
        default:
            break
        }
    }

    private func startAudioLoop() {
        let stream = lease.buffers
        let preRoll = lease.preRoll

        audioTask = Task { [weak self] in
            guard let self else { return }
            // Send the pre-roll first — these are the buffers captured BEFORE
            // hotkey-down so the user's first word survives Bluetooth HFP and
            // mic warm-up latencies.
            for buffer in preRoll {
                if Task.isCancelled { return }
                await self.sendBuffer(buffer)
            }
            for await buffer in stream {
                if Task.isCancelled { return }
                await self.sendBuffer(buffer)
            }
        }
    }

    private func sendBuffer(_ buffer: AVAudioPCMBuffer) async {
        guard let pcm16 = LINEAR16Encoder.encode(buffer) else { return }
        do {
            try await provider.send(pcm16: pcm16)
        } catch {
            sessionLog.warning("[Session \(self.id.uuidString, privacy: .public)] audio send failed")
        }
    }

    private func releaseLeaseIfNeeded() async {
        if let host = hostRef {
            await host.release(lease)
        }
    }
}

