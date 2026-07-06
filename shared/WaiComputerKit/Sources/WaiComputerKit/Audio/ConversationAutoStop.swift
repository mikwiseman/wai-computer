import Foundation
import AVFoundation

/// Energy-based speech-activity estimator with an adaptive noise floor.
///
/// Works on per-buffer RMS values (one value per ~160 ms capture flush).
/// The floor tracks the 20th percentile of a sliding window, so natural
/// pauses between words keep it anchored at the room-tone level even during
/// long stretches of continuous conversation. Detection requires both a
/// relative margin over the floor and an absolute minimum level, so a
/// dead-silent room never promotes electronics noise to "speech".
public struct SpeechActivityEstimator: Sendable {
    /// dB over the adaptive floor a frame must reach to count as speech.
    private let activationMarginDb: Float
    /// Absolute dBFS gate below which nothing counts as speech.
    private let absoluteMinDb: Float
    /// Absolute dBFS level that always counts as speech. Caps the adaptive
    /// threshold so a window saturated with continuous loud speech (webinar,
    /// monologue) can never raise the floor high enough to stop detecting
    /// the very speech that saturated it.
    private let speechCeilingDb: Float
    /// Sliding window of recent frame levels (~41 s at 160 ms cadence).
    private let windowCapacity: Int

    private var window: [Float] = []
    private var nextSlot = 0

    /// Snapshot of the last classification, for diagnostics/logging.
    public private(set) var lastLevelDb: Float = -100
    public private(set) var lastThresholdDb: Float = -100

    public init(
        activationMarginDb: Float = 10,
        absoluteMinDb: Float = -50,
        speechCeilingDb: Float = -35,
        windowCapacity: Int = 256
    ) {
        self.activationMarginDb = activationMarginDb
        self.absoluteMinDb = absoluteMinDb
        self.speechCeilingDb = speechCeilingDb
        self.windowCapacity = max(windowCapacity, 8)
    }

    /// Classify one capture buffer by its linear RMS level and fold it into
    /// the adaptive floor.
    public mutating func isSpeech(rms: Float) -> Bool {
        let levelDb = Self.decibels(fromRMS: rms)
        let floorDb = noiseFloorDb()
        record(levelDb)
        let threshold = max(min(floorDb + activationMarginDb, speechCeilingDb), absoluteMinDb)
        lastLevelDb = levelDb
        lastThresholdDb = threshold
        return levelDb >= threshold
    }

    /// 20th percentile of the sliding window; a conservative default before
    /// the window has any history.
    private func noiseFloorDb() -> Float {
        guard !window.isEmpty else { return -70 }
        let sorted = window.sorted()
        let index = Int(Float(sorted.count - 1) * 0.2)
        return sorted[index]
    }

    private mutating func record(_ levelDb: Float) {
        if window.count < windowCapacity {
            window.append(levelDb)
        } else {
            window[nextSlot] = levelDb
            nextSlot = (nextSlot + 1) % windowCapacity
        }
    }

    static func decibels(fromRMS rms: Float) -> Float {
        20 * log10(max(rms, 1e-7))
    }

    /// Linear RMS of the loudest channel of a PCM buffer. Multichannel
    /// recordings (mic + system audio) count as active when either side
    /// carries signal.
    public static func peakChannelRMS(of buffer: AVAudioPCMBuffer) -> Float {
        guard let channelData = buffer.floatChannelData else { return 0 }
        let frames = Int(buffer.frameLength)
        let channels = Int(buffer.format.channelCount)
        guard frames > 0, channels > 0 else { return 0 }

        var peak: Float = 0
        for channel in 0..<channels {
            let samples = channelData[channel]
            var sum: Float = 0
            for frame in 0..<frames {
                let sample = samples[frame]
                sum += sample * sample
            }
            peak = max(peak, (sum / Float(frames)).squareRoot())
        }
        return peak
    }
}

/// Why the end-of-conversation prompt fired.
public enum ConversationEndReason: String, Equatable, Sendable {
    /// Nothing that sounds like speech for the configured window.
    case silence
    /// An external signal reported the call ended (e.g. the meeting app
    /// released the microphone), confirmed by a short quiet window.
    case callEnded
}

/// Event emitted by `ConversationAutoStopMonitor.tick(at:)`.
public enum ConversationAutoStopEvent: Equatable, Sendable {
    /// Show the "conversation seems over" prompt with a countdown.
    case beginPrompt(ConversationEndReason)
    /// Speech resumed while the prompt was up — dismiss it.
    case cancelPrompt
    /// The countdown expired with no interaction — perform the auto action.
    case autoStop(ConversationEndReason)
}

public struct ConversationAutoStopConfig: Equatable, Sendable {
    /// Continuous quiet time before the end-of-conversation prompt.
    public var silenceTimeout: TimeInterval
    /// Quiet time after an external call-ended signal before prompting.
    public var callEndedTimeout: TimeInterval
    /// How long the prompt waits for a human before auto-stopping.
    public var countdown: TimeInterval
    /// Consecutive speech-level frames (~160 ms each) required to count as
    /// real voice. Short bursts — door slams, chair creaks, keyboard runs —
    /// span a frame or two and must NOT reset the silence clock; actual
    /// speech utterances sustain well past this.
    public var sustainedSpeechFrames: Int

    public init(
        silenceTimeout: TimeInterval,
        callEndedTimeout: TimeInterval,
        countdown: TimeInterval,
        sustainedSpeechFrames: Int = 4
    ) {
        self.silenceTimeout = silenceTimeout
        self.callEndedTimeout = callEndedTimeout
        self.countdown = countdown
        self.sustainedSpeechFrames = sustainedSpeechFrames
    }

    public static let `default` = ConversationAutoStopConfig(
        silenceTimeout: 240,
        callEndedTimeout: 30,
        countdown: 60
    )
}

/// Decides when a recording should end because the conversation is over.
///
/// Thread-safe by a single lock: the audio pipeline feeds `recordAudioLevel`
/// from its capture task while the UI timer calls `tick` on the main actor.
/// The monitor never stops anything itself — it emits events and the owner
/// (the recording view model) shows the prompt and performs the stop/pause.
public final class ConversationAutoStopMonitor: @unchecked Sendable {
    private enum State: Equatable {
        case monitoring
        case prompting(since: Date, reason: ConversationEndReason)
        case finished
    }

    private let config: ConversationAutoStopConfig
    private let lock = NSLock()

    private var state: State = .monitoring
    private var estimator: SpeechActivityEstimator
    private var lastVoiceAt: Date
    private var callEndedAt: Date?
    private var isPausedFlag = false
    private var consecutiveSpeechFrames = 0

    public init(
        config: ConversationAutoStopConfig = .default,
        estimator: SpeechActivityEstimator = SpeechActivityEstimator(),
        now: Date = Date()
    ) {
        self.config = config
        self.estimator = estimator
        self.lastVoiceAt = now
    }

    public var isPrompting: Bool {
        lock.lock()
        defer { lock.unlock() }
        if case .prompting = state { return true }
        return false
    }

    /// Seconds since the last detected voice activity. Diagnostic/UI aid.
    public func secondsSinceLastVoice(at date: Date) -> TimeInterval {
        lock.lock()
        defer { lock.unlock() }
        return date.timeIntervalSince(lastVoiceAt)
    }

    /// Whether an external call-ended signal is pending confirmation.
    public var hasPendingCallEnded: Bool {
        lock.lock()
        defer { lock.unlock() }
        return callEndedAt != nil
    }

    /// Last classified audio level and the threshold it was compared to (dBFS).
    public var levelDiagnostics: (levelDb: Float, thresholdDb: Float) {
        lock.lock()
        defer { lock.unlock() }
        return (estimator.lastLevelDb, estimator.lastThresholdDb)
    }

    /// Feed one capture buffer's linear RMS level. Only sustained
    /// speech-level audio (`sustainedSpeechFrames` consecutive frames)
    /// counts as voice; short pops and creaks do not reset the clock.
    public func recordAudioLevel(rms: Float, at date: Date) {
        lock.lock()
        defer { lock.unlock() }
        guard !isPausedFlag, state != .finished else { return }

        if estimator.isSpeech(rms: rms) {
            consecutiveSpeechFrames += 1
            if consecutiveSpeechFrames >= config.sustainedSpeechFrames {
                lastVoiceAt = date
                callEndedAt = nil
            }
        } else {
            consecutiveSpeechFrames = 0
        }
    }

    /// External end-of-call signal (the meeting app released the microphone).
    public func noteCallEnded(at date: Date) {
        lock.lock()
        defer { lock.unlock() }
        guard !isPausedFlag, state != .finished else { return }
        callEndedAt = date
    }

    /// External call-started signal — clears any pending end-of-call fast path.
    public func noteCallActive(at date: Date) {
        lock.lock()
        defer { lock.unlock() }
        callEndedAt = nil
    }

    /// Pause suspends monitoring entirely; resume re-arms from the resume
    /// moment so hours spent paused never count as silence.
    public func setPaused(_ paused: Bool, at date: Date) {
        lock.lock()
        defer { lock.unlock() }
        isPausedFlag = paused
        if paused {
            if case .prompting = state {
                state = .monitoring
            }
        } else {
            state = .monitoring
            lastVoiceAt = date
            callEndedAt = nil
            consecutiveSpeechFrames = 0
        }
    }

    /// The user said the conversation is still going — dismiss the prompt and
    /// re-arm the full silence window.
    public func userContinued(at date: Date) {
        lock.lock()
        defer { lock.unlock() }
        guard state != .finished else { return }
        state = .monitoring
        lastVoiceAt = date
        callEndedAt = nil
        consecutiveSpeechFrames = 0
    }

    /// Advance the state machine. Call about once a second.
    public func tick(at date: Date) -> ConversationAutoStopEvent? {
        lock.lock()
        defer { lock.unlock() }
        guard !isPausedFlag else { return nil }

        switch state {
        case .finished:
            return nil

        case .monitoring:
            if let endedAt = callEndedAt,
               date.timeIntervalSince(max(endedAt, lastVoiceAt)) >= config.callEndedTimeout {
                state = .prompting(since: date, reason: .callEnded)
                return .beginPrompt(.callEnded)
            }
            if date.timeIntervalSince(lastVoiceAt) >= config.silenceTimeout {
                state = .prompting(since: date, reason: .silence)
                return .beginPrompt(.silence)
            }
            return nil

        case .prompting(let since, let reason):
            if lastVoiceAt > since {
                state = .monitoring
                return .cancelPrompt
            }
            if date.timeIntervalSince(since) >= config.countdown {
                state = .finished
                return .autoStop(reason)
            }
            return nil
        }
    }

    /// Seconds left on the prompt countdown, or nil when no prompt is up.
    public func promptCountdownRemaining(at date: Date) -> TimeInterval? {
        lock.lock()
        defer { lock.unlock() }
        guard case .prompting(let since, _) = state else { return nil }
        return max(0, config.countdown - date.timeIntervalSince(since))
    }
}
