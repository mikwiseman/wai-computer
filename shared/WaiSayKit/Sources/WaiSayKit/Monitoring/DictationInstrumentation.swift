import Foundation
import os.log
import os.signpost
import Sentry

/// Centralised instrumentation for the dictation flow.
///
/// One `DictationInstrumentation.Session` is created per push-to-talk press.
/// Every life-cycle event is recorded as:
///   • an OSLog signpost (Instruments flame chart) ,
///   • a Sentry breadcrumb with `sessionId` + `elapsedMs` (privacy-safe — no
///     transcript text, no token, no audio bytes) ,
///   • aggregate counters that drive the "consecutive_failures" warning.
///
/// The class is process-singleton, thread-safe, and never blocks a caller.
public final class DictationInstrumentation: @unchecked Sendable {
    public static let shared = DictationInstrumentation()

    public static let signpostLog = OSLog(
        subsystem: "is.waiwai.say.dictation",
        category: .pointsOfInterest
    )

    /// Process-lifetime aggregate counters. Read on the main actor; mutated
    /// only inside the `lock`.
    public struct Counters: Sendable {
        public var sessionsStarted: Int = 0
        public var sessionsSucceeded: Int = 0
        public var sessionsFailed: Int = 0
        public var sessionsCancelled: Int = 0
        public var consecutiveFailures: Int = 0
        /// First-token latency samples (ms). Bounded ring buffer (last 50).
        public var firstTokenLatencyMs: [Int] = []
        /// Total latency samples (ms) — hotkey to insertion. Bounded.
        public var totalLatencyMs: [Int] = []
    }

    private let lock = NSLock()
    private var counters = Counters()
    private static let latencyRingSize = 50

    private init() {}

    public func snapshot() -> Counters {
        lock.lock()
        defer { lock.unlock() }
        return counters
    }

    public func startSession() -> Session {
        lock.lock()
        counters.sessionsStarted += 1
        lock.unlock()

        let session = Session()
        session.event(.armingStarted, data: ["sessionsStartedSinceLaunch": counters.sessionsStarted])
        return session
    }

    fileprivate func recordOutcome(_ outcome: SessionOutcome, totalMs: Int?, firstTokenMs: Int?) {
        lock.lock()
        defer { lock.unlock() }
        switch outcome {
        case .succeeded:
            counters.sessionsSucceeded += 1
            counters.consecutiveFailures = 0
            if let totalMs { record(&counters.totalLatencyMs, totalMs) }
            if let firstTokenMs { record(&counters.firstTokenLatencyMs, firstTokenMs) }
        case .failed:
            counters.sessionsFailed += 1
            counters.consecutiveFailures += 1
        case .cancelled:
            counters.sessionsCancelled += 1
            counters.consecutiveFailures = 0
        }
    }

    private func record(_ buffer: inout [Int], _ sample: Int) {
        buffer.append(sample)
        if buffer.count > Self.latencyRingSize {
            buffer.removeFirst(buffer.count - Self.latencyRingSize)
        }
    }

    public func consecutiveFailureCount() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return counters.consecutiveFailures
    }
}

public extension DictationInstrumentation {
    enum SessionOutcome: Sendable { case succeeded, failed, cancelled }

    /// Per-press session. Owns the sessionId and origin timestamp; emits
    /// breadcrumbs and signposts. Created via `DictationInstrumentation.shared.startSession()`.
    final class Session: @unchecked Sendable {
        public let id = UUID()
        public let startedAt: ContinuousClock.Instant
        private let signpostID: OSSignpostID
        private var firstTokenLatencyMs: Int?
        private let lock = NSLock()
        private var finalised = false

        init() {
            self.startedAt = ContinuousClock().now
            self.signpostID = OSSignpostID(log: DictationInstrumentation.signpostLog)
            os_signpost(
                .begin,
                log: DictationInstrumentation.signpostLog,
                name: "DictationSession",
                signpostID: signpostID,
                "%{public}@", id.uuidString
            )
        }

        public func event(_ event: Event, data: [String: Any] = [:]) {
            let elapsedMs = elapsedMillis()
            os_signpost(
                .event,
                log: DictationInstrumentation.signpostLog,
                name: "DictationSession",
                signpostID: signpostID,
                "%{public}@ +%dms",
                event.rawValue, elapsedMs
            )

            if event == .firstTokenReceived {
                lock.lock()
                if firstTokenLatencyMs == nil { firstTokenLatencyMs = elapsedMs }
                lock.unlock()
            }

            var crumbData: [String: Any] = data
            crumbData["sessionId"] = id.uuidString
            crumbData["elapsedMs"] = elapsedMs

            SentryHelper.addBreadcrumb(
                category: event.category,
                message: event.rawValue,
                level: event.level,
                data: crumbData
            )
        }

        public func failure(_ error: Error, extras: [String: Any] = [:]) {
            let elapsedMs = elapsedMillis()
            var allExtras: [String: Any] = extras
            allExtras["sessionId"] = id.uuidString
            allExtras["elapsedMs"] = elapsedMs
            SentryHelper.captureError(error, extras: allExtras)
            finish(outcome: .failed)
        }

        public func cancel(reason: String) {
            event(.sessionCancelled, data: ["reason": reason])
            finish(outcome: .cancelled)
        }

        public func succeed() {
            let totalMs = elapsedMillis()
            event(.sessionCompleted, data: ["totalMs": totalMs])
            finish(outcome: .succeeded, totalMs: totalMs)
        }

        private func finish(outcome: SessionOutcome, totalMs: Int? = nil) {
            lock.lock()
            guard !finalised else { lock.unlock(); return }
            finalised = true
            let firstToken = firstTokenLatencyMs
            lock.unlock()

            os_signpost(
                .end,
                log: DictationInstrumentation.signpostLog,
                name: "DictationSession",
                signpostID: signpostID,
                "%{public}@ %{public}@",
                id.uuidString,
                String(describing: outcome)
            )

            DictationInstrumentation.shared.recordOutcome(
                outcome,
                totalMs: totalMs,
                firstTokenMs: firstToken
            )

            // Surface a Sentry warning when 3+ consecutive failures cluster.
            // Useful canary for "diктовка отвалилась" reports.
            if outcome == .failed,
               DictationInstrumentation.shared.consecutiveFailureCount() >= 3 {
                SentryHelper.addBreadcrumb(
                    category: "dictation.session",
                    message: "consecutive_failures",
                    level: .warning,
                    data: ["count": DictationInstrumentation.shared.consecutiveFailureCount()]
                )
            }
        }

        private func elapsedMillis() -> Int {
            let elapsed = ContinuousClock().now - startedAt
            return Int(elapsed.components.seconds * 1_000) +
                Int(elapsed.components.attoseconds / 1_000_000_000_000_000)
        }
    }

    enum Event: String, Sendable {
        case armingStarted = "arming.start"
        case audioLeaseAcquired = "audio.lease.acquired"
        case audioLeaseReleased = "audio.lease.released"
        case audioFirstChunkSent = "audio.first_chunk_sent"
        case audioContinuationDropped = "audio.continuation.dropped"
        case tokenMinted = "token.minted"
        case tokenPrefetchHit = "token.prefetch.hit"
        case tokenPrefetchMiss = "token.prefetch.miss"
        case providerConnecting = "provider.connecting"
        case providerOpened = "provider.opened"
        case providerWarning = "provider.warning"
        case providerClosed = "provider.closed"
        case firstTokenReceived = "transcript.first_token"
        case interimTranscript = "transcript.interim"
        case committedTranscript = "transcript.committed"
        case finalizingStarted = "finalizing.start"
        case transcriptFinalized = "transcript.finalized"
        case cleanupRequested = "cleanup.requested"
        case cleanupCompleted = "cleanup.completed"
        case cleanupSkipped = "cleanup.skipped"
        case insertionStarted = "insertion.start"
        case insertionCompleted = "insertion.completed"
        case sessionCompleted = "session.completed"
        case sessionCancelled = "session.cancelled"

        var category: String {
            switch self {
            case .armingStarted, .audioFirstChunkSent, .finalizingStarted,
                 .transcriptFinalized, .insertionStarted, .insertionCompleted,
                 .sessionCompleted, .sessionCancelled:
                return "dictation.session"
            case .audioLeaseAcquired, .audioLeaseReleased, .audioContinuationDropped:
                return "dictation.audio"
            case .tokenMinted, .tokenPrefetchHit, .tokenPrefetchMiss:
                return "dictation.token"
            case .providerConnecting, .providerOpened, .providerWarning,
                 .providerClosed, .firstTokenReceived, .interimTranscript,
                 .committedTranscript:
                return "dictation.provider"
            case .cleanupRequested, .cleanupCompleted, .cleanupSkipped:
                return "dictation.cleanup"
            }
        }

        var level: SentryLevel {
            switch self {
            case .providerWarning, .audioContinuationDropped, .tokenPrefetchMiss,
                 .sessionCancelled:
                return .warning
            default:
                return .info
            }
        }
    }
}

/// Lightweight typed errors used by the instrumentation layer when an
/// operation cannot produce a more specific provider-level error.
public enum DictationInstrumentationError: Error, LocalizedError {
    case microphoneDenied
    case notAuthenticated
    case unknown(String)

    public var errorDescription: String? {
        switch self {
        case .microphoneDenied: return "Microphone permission denied"
        case .notAuthenticated: return "Not authenticated"
        case .unknown(let detail): return "Dictation failed: \(detail)"
        }
    }
}
