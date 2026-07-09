import Foundation
import AVFoundation

/// One sound-classifier window verdict over ~1 s of captured audio.
///
/// Produced by `SoundAnalysisSpeechDetector` every ~0.5 s (windows overlap by
/// half). `speechConfidence` comes from the system sound classifier's
/// "speech" class; `levelDb` is the peak buffer RMS (dBFS) observed while the
/// window accumulated, so silent-but-confident quirks can be gated out.
public struct SpeechWindowObservation: Equatable, Sendable {
    public let speechConfidence: Double
    public let levelDb: Float

    public init(speechConfidence: Double, levelDb: Float) {
        self.speechConfidence = speechConfidence
        self.levelDb = levelDb
    }
}

/// Linear-RMS helpers shared by the capture pipeline and the detector.
public enum AudioLevelMeter {
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

    public static func decibels(fromRMS rms: Float) -> Float {
        20 * log10(max(rms, 1e-7))
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
    /// Classifier confidence at/above which a window counts as speech.
    /// On-device measurements: real speech ≥ 0.95, music ≈ 0.01, typing ≈
    /// 0.03, pink noise ≈ 0.10, digital silence ≈ 0.20 flat.
    public var speechConfidenceThreshold: Double
    /// Absolute dBFS gate — windows quieter than this are never speech, no
    /// matter what the classifier thinks (guards the silence prior).
    public var speechMinLevelDb: Float
    /// Consecutive speech windows (~0.5 s cadence) required to count as real
    /// voice. A lone confident window — a stray shout, one TV line bleeding
    /// through — must not reset the silence clock; conversation sustains.
    public var sustainedSpeechWindows: Int

    public init(
        silenceTimeout: TimeInterval,
        callEndedTimeout: TimeInterval,
        countdown: TimeInterval,
        speechConfidenceThreshold: Double = 0.6,
        speechMinLevelDb: Float = -55,
        sustainedSpeechWindows: Int = 2
    ) {
        self.silenceTimeout = silenceTimeout
        self.callEndedTimeout = callEndedTimeout
        self.countdown = countdown
        self.speechConfidenceThreshold = speechConfidenceThreshold
        self.speechMinLevelDb = speechMinLevelDb
        self.sustainedSpeechWindows = sustainedSpeechWindows
    }

    public static let `default` = ConversationAutoStopConfig(
        silenceTimeout: 240,
        callEndedTimeout: 30,
        countdown: 60
    )

    /// Whether one classifier window counts as speech: confident AND audible.
    public func isSpeech(_ observation: SpeechWindowObservation) -> Bool {
        observation.speechConfidence >= speechConfidenceThreshold
            && observation.levelDb >= speechMinLevelDb
    }
}

/// Decides when a recording should end because the conversation is over.
///
/// Thread-safe by a single lock: the speech detector feeds
/// `recordSpeechWindow` from the analysis thread while the UI timer calls
/// `tick` on the main actor. The monitor never stops anything itself — it
/// emits events and the owner (the recording view model) shows the prompt and
/// performs the stop/pause.
public final class ConversationAutoStopMonitor: @unchecked Sendable {
    private enum State: Equatable {
        case monitoring
        case prompting(since: Date, reason: ConversationEndReason)
        case finished
    }

    /// How long after the last confirmed speech window the "voice active"
    /// UI surface stays lit. Windows arrive every ~0.5 s; a short decay keeps
    /// the indicator honest without flickering between utterances.
    private static let voiceActiveDecay: TimeInterval = 5

    private let config: ConversationAutoStopConfig
    private let lock = NSLock()

    private var state: State = .monitoring
    private var lastVoiceAt: Date
    private var callEndedAt: Date?
    private var isPausedFlag = false
    private var consecutiveSpeechWindows = 0
    private var lastObservation: SpeechWindowObservation?
    private var startedAt: Date

    public init(
        config: ConversationAutoStopConfig = .default,
        now: Date = Date()
    ) {
        self.config = config
        self.lastVoiceAt = now
        self.startedAt = now
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

    /// Whether sustained voice was confirmed within the last few seconds —
    /// drives the live "hearing voice" indicator in the recording UI.
    public func isVoiceActive(at date: Date) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard lastVoiceAt > startedAt else { return false }
        return date.timeIntervalSince(lastVoiceAt) < Self.voiceActiveDecay
    }

    /// Whether an external call-ended signal is pending confirmation.
    public var hasPendingCallEnded: Bool {
        lock.lock()
        defer { lock.unlock() }
        return callEndedAt != nil
    }

    /// Last classifier window received, for diagnostics/logging.
    public var lastWindowDiagnostics: SpeechWindowObservation? {
        lock.lock()
        defer { lock.unlock() }
        return lastObservation
    }

    /// Feed one classifier window. Only sustained speech
    /// (`sustainedSpeechWindows` consecutive confident windows) counts as
    /// voice; lone confident windows and loud non-speech do not reset the
    /// silence clock.
    public func recordSpeechWindow(_ observation: SpeechWindowObservation, at date: Date) {
        lock.lock()
        defer { lock.unlock() }
        guard !isPausedFlag, state != .finished else { return }

        lastObservation = observation
        if config.isSpeech(observation) {
            consecutiveSpeechWindows += 1
            if consecutiveSpeechWindows >= config.sustainedSpeechWindows {
                lastVoiceAt = date
                callEndedAt = nil
            }
        } else {
            consecutiveSpeechWindows = 0
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
            startedAt = date
            callEndedAt = nil
            consecutiveSpeechWindows = 0
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
        startedAt = date
        callEndedAt = nil
        consecutiveSpeechWindows = 0
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
