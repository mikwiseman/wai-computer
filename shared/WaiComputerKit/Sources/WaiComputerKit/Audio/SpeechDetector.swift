import Foundation
import AVFoundation
import SoundAnalysis
import os

private let speechLog = Logger(subsystem: "is.waiwai.computer.kit", category: "speech-detect")

/// On-device speech detection over the capture buffer stream, backed by the
/// system sound classifier (`SNClassifySoundRequest`, 300+ classes, built into
/// macOS 12+/iOS 15+ — no bundled model, no network).
///
/// Feed every capture buffer via `process(_:)` from a single task; roughly
/// every half second the classifier emits one `SpeechWindowObservation`
/// (window ≈ 1 s, overlap 0.5) through `onWindow`, on the analysis thread.
///
/// The classifier only reads channel 0 of whatever it is fed — verified
/// on-device: speech living solely in channel 1 scores as silence. Capture
/// buffers can be 2-channel (mic + system audio), so every buffer is folded
/// to mono here before analysis.
public final class SoundAnalysisSpeechDetector: @unchecked Sendable {
    private let request: SNClassifySoundRequest
    private let onWindow: @Sendable (SpeechWindowObservation) -> Void

    private let lock = NSLock()
    private var analyzer: SNAudioStreamAnalyzer?
    private var analyzerFormat: AVAudioFormat?
    private var framePosition: AVAudioFramePosition = 0
    private var windowPeakRMS: Float = 0
    private var observer: WindowObserver?

    /// Fails only when the system classifier is unavailable — the caller must
    /// surface that and disable audio-based auto-stop, not fall back to a
    /// level heuristic.
    public init(onWindow: @escaping @Sendable (SpeechWindowObservation) -> Void) throws {
        self.request = try SNClassifySoundRequest(classifierIdentifier: .version1)
        self.onWindow = onWindow

        // ~1 s windows at half overlap → a verdict every ~0.5 s. The window
        // duration must come from the model's supported set.
        let desired = 0.975
        switch request.windowDurationConstraint {
        case .enumeratedDurations(let durations):
            let seconds = durations.map(\.seconds)
            if let closest = seconds.min(by: { abs($0 - desired) < abs($1 - desired) }) {
                request.windowDuration = CMTime(seconds: closest, preferredTimescale: 48_000)
            }
        case .durationRange(let range):
            let clamped = min(max(desired, range.start.seconds), range.end.seconds)
            request.windowDuration = CMTime(seconds: clamped, preferredTimescale: 48_000)
        @unknown default:
            break
        }
        request.overlapFactor = 0.5
    }

    /// Fold a capture buffer into the analyzer. Call sequentially from the
    /// capture loop; the classifier work costs well under 1% of a core.
    public func process(_ buffer: AVAudioPCMBuffer) {
        guard let mono = Self.monoMixdown(of: buffer) else { return }

        lock.lock()
        windowPeakRMS = max(windowPeakRMS, AudioLevelMeter.peakChannelRMS(of: buffer))
        let analyzer = ensureAnalyzerLocked(for: mono.format)
        let position = framePosition
        framePosition += AVAudioFramePosition(mono.frameLength)
        lock.unlock()

        analyzer?.analyze(mono, atAudioFramePosition: position)
    }

    /// Flush any pending window and stop analysis.
    public func finish() {
        lock.lock()
        let analyzer = self.analyzer
        self.analyzer = nil
        self.observer = nil
        self.analyzerFormat = nil
        lock.unlock()
        analyzer?.completeAnalysis()
    }

    /// Average all channels into one; passes mono buffers through untouched.
    static func monoMixdown(of buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        let channels = Int(buffer.format.channelCount)
        guard channels > 1 else { return buffer }
        guard let source = buffer.floatChannelData else { return nil }
        let frames = Int(buffer.frameLength)
        guard
            let format = AVAudioFormat(
                commonFormat: .pcmFormatFloat32,
                sampleRate: buffer.format.sampleRate,
                channels: 1,
                interleaved: false
            ),
            let mono = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)),
            let target = mono.floatChannelData
        else { return nil }

        mono.frameLength = AVAudioFrameCount(frames)
        let scale = 1 / Float(channels)
        for frame in 0..<frames {
            var sum: Float = 0
            for channel in 0..<channels {
                sum += source[channel][frame]
            }
            target[0][frame] = sum * scale
        }
        return mono
    }

    /// Analyzer bound to the current stream format; rebuilt if the format
    /// ever changes mid-stream (capture restarts with new hardware).
    private func ensureAnalyzerLocked(for format: AVAudioFormat) -> SNAudioStreamAnalyzer? {
        if let analyzer, analyzerFormat == format {
            return analyzer
        }
        if analyzer != nil {
            speechLog.warning("Stream format changed mid-recording — rebuilding analyzer")
            analyzer?.completeAnalysis()
        }
        let fresh = SNAudioStreamAnalyzer(format: format)
        let observer = WindowObserver { [weak self] confidence in
            self?.emitWindow(confidence: confidence)
        }
        do {
            try fresh.add(request, withObserver: observer)
        } catch {
            speechLog.error("Failed to attach classifier request: \(error, privacy: .public)")
            return nil
        }
        self.analyzer = fresh
        self.analyzerFormat = format
        self.observer = observer
        self.framePosition = 0
        return fresh
    }

    private func emitWindow(confidence: Double) {
        lock.lock()
        let peak = windowPeakRMS
        windowPeakRMS = 0
        lock.unlock()
        onWindow(SpeechWindowObservation(
            speechConfidence: confidence,
            levelDb: AudioLevelMeter.decibels(fromRMS: peak)
        ))
    }

    private final class WindowObserver: NSObject, SNResultsObserving {
        private let onSpeechConfidence: (Double) -> Void

        init(onSpeechConfidence: @escaping (Double) -> Void) {
            self.onSpeechConfidence = onSpeechConfidence
        }

        func request(_ request: SNRequest, didProduce result: SNResult) {
            guard let result = result as? SNClassificationResult else { return }
            let confidence = result.classification(forIdentifier: "speech")?.confidence ?? 0
            onSpeechConfidence(confidence)
        }

        func request(_ request: SNRequest, didFailWithError error: Error) {
            speechLog.error("Sound classification failed: \(error, privacy: .public)")
        }
    }
}
