#if canImport(AVFoundation)
import AVFoundation
import Foundation

/// Offline, on-device read-aloud via `AVSpeechSynthesizer` ($0, no network, no
/// PII egress — the text was already produced server-side). `speak` resolves
/// when the utterance finishes; `stop` is immediate barge-in. The continuation
/// is lock-guarded and resumed exactly once so a finish/cancel race cannot
/// double-resume or leak.
public final class AVSpeechTTSProvider: NSObject, TTSProvider, @unchecked Sendable {
    private let synthesizer = AVSpeechSynthesizer()
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Never>?
    private let language: String
    private let rate: Float

    public init(
        language: String = "en-US",
        rate: Float = AVSpeechUtteranceDefaultSpeechRate
    ) {
        self.language = language
        self.rate = rate
        super.init()
        synthesizer.delegate = self
    }

    public func speak(_ sentence: String) async {
        await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
            lock.lock()
            let stale = continuation
            continuation = cont
            lock.unlock()
            // Defensively resume any leftover continuation (never await forever).
            stale?.resume()

            let utterance = AVSpeechUtterance(string: sentence)
            let voiceLanguage = Self.resolvedVoiceLanguage(for: sentence, default: language)
            utterance.voice = AVSpeechSynthesisVoice(language: voiceLanguage)
            utterance.rate = rate
            synthesizer.speak(utterance)
        }
    }

    public func stop() {
        synthesizer.stopSpeaking(at: .immediate)
        resumePending()
    }

    /// Pick the voice language per utterance from its content: Cyrillic-dominant
    /// text gets a Russian voice, everything else the configured default. The
    /// answer's actual language is the truth here — not an app/system setting —
    /// so a Russian reply is never read aloud by an English voice.
    static func resolvedVoiceLanguage(for text: String, default defaultLanguage: String) -> String {
        var cyrillic = 0
        var latin = 0
        for scalar in text.unicodeScalars {
            if scalar.value >= 0x0400 && scalar.value <= 0x04FF {
                cyrillic += 1
            } else if (scalar.value >= 0x41 && scalar.value <= 0x5A)
                || (scalar.value >= 0x61 && scalar.value <= 0x7A)
            {
                latin += 1
            }
        }
        guard cyrillic > 0 else { return defaultLanguage }
        return cyrillic >= latin ? "ru-RU" : defaultLanguage
    }

    private func resumePending() {
        lock.lock()
        let cont = continuation
        continuation = nil
        lock.unlock()
        cont?.resume()
    }
}

extension AVSpeechTTSProvider: AVSpeechSynthesizerDelegate {
    public func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didFinish utterance: AVSpeechUtterance
    ) {
        resumePending()
    }

    public func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didCancel utterance: AVSpeechUtterance
    ) {
        resumePending()
    }
}
#endif
