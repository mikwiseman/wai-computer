import Foundation

/// Accumulates "the local user is speaking" intervals from the raw microphone
/// stream while it is still separable from system audio (pre-mix).
///
/// The clock is FRAME-based (frames fed / sample rate), so intervals line up
/// with the recorded audio file and the transcript timeline exactly — wall
/// time would drift across pauses and stalls.
///
/// The gate is deliberately simple and dependency-free: a flush window counts
/// as local speech when the mic RMS clears an absolute floor AND dominates
/// the system-audio RMS. Without echo cancellation, remote voices leak into
/// the mic at a fraction of direct-voice level; the dominance ratio filters
/// that leak without ML.
public struct LocalSpeechTracker: Sendable {
    /// Mic RMS below this is ambient noise, never speech (~-46 dBFS).
    public static let defaultActivationRMS: Float = 0.005
    /// Mic must be this many times louder than system audio to count as the
    /// local user (echo leak sits well below direct voice at normal volumes).
    public static let defaultDominanceRatio: Float = 1.6
    /// Gaps shorter than this merge into one interval (breath pauses).
    public static let defaultMergeGapMs = 600
    /// Intervals shorter than this are dropped (keyboard clicks, coughs).
    public static let defaultMinIntervalMs = 300

    private let sampleRate: Double
    private let activationRMS: Float
    private let dominanceRatio: Float
    private let mergeGapMs: Int
    private let minIntervalMs: Int

    private var framesSeen: Int = 0
    private var intervals: [(start: Int, end: Int)] = []
    private var currentStartMs: Int?
    private var currentEndMs: Int = 0

    public init(
        sampleRate: Double,
        activationRMS: Float = LocalSpeechTracker.defaultActivationRMS,
        dominanceRatio: Float = LocalSpeechTracker.defaultDominanceRatio,
        mergeGapMs: Int = LocalSpeechTracker.defaultMergeGapMs,
        minIntervalMs: Int = LocalSpeechTracker.defaultMinIntervalMs
    ) {
        self.sampleRate = sampleRate
        self.activationRMS = activationRMS
        self.dominanceRatio = dominanceRatio
        self.mergeGapMs = mergeGapMs
        self.minIntervalMs = minIntervalMs
    }

    /// Feed one flush window of pre-mix samples. `system` may be empty when
    /// system audio is unavailable; the dominance gate then compares to zero.
    public mutating func ingest(mic: [Float], system: [Float]) {
        let frames = mic.count
        guard frames > 0 else { return }
        let windowStartMs = Self.milliseconds(fromFrames: framesSeen, sampleRate: sampleRate)
        framesSeen += frames
        let windowEndMs = Self.milliseconds(fromFrames: framesSeen, sampleRate: sampleRate)

        let micRMS = Self.rms(mic)
        let systemRMS = system.isEmpty ? 0 : Self.rms(system)
        let isLocalSpeech = micRMS >= activationRMS && micRMS >= systemRMS * dominanceRatio

        if isLocalSpeech {
            if currentStartMs == nil {
                currentStartMs = windowStartMs
            }
            currentEndMs = windowEndMs
        } else if let start = currentStartMs {
            let silenceMs = windowEndMs - currentEndMs
            if silenceMs > mergeGapMs {
                closeInterval(start: start)
            }
        }
    }

    /// Finish tracking and return merged `[start_ms, end_ms]` intervals.
    public mutating func finish() -> [[Int]] {
        if let start = currentStartMs {
            closeInterval(start: start)
        }
        return intervals.map { [$0.start, $0.end] }
    }

    private mutating func closeInterval(start: Int) {
        defer {
            currentStartMs = nil
            currentEndMs = 0
        }
        guard currentEndMs - start >= minIntervalMs else { return }
        if let last = intervals.last, start - last.end <= mergeGapMs {
            intervals[intervals.count - 1].end = currentEndMs
        } else {
            intervals.append((start: start, end: currentEndMs))
        }
    }

    static func rms(_ samples: [Float]) -> Float {
        guard !samples.isEmpty else { return 0 }
        var sum: Float = 0
        for sample in samples {
            sum += sample * sample
        }
        return (sum / Float(samples.count)).squareRoot()
    }

    static func milliseconds(fromFrames frames: Int, sampleRate: Double) -> Int {
        guard sampleRate > 0 else { return 0 }
        return Int((Double(frames) * 1000.0 / sampleRate).rounded())
    }
}

/// Builds the capture sidecar JSON the backend consumes
/// (see backend/app/core/capture_metadata.py — schema version 1).
public enum CaptureSidecar {
    public static func json(
        capture: String,
        localSpeechIntervalsMs: [[Int]],
        aec: Bool = false
    ) -> String? {
        let payload: [String: Any] = [
            "version": 1,
            "capture": capture,
            "local_speech_ms": localSpeechIntervalsMs,
            "aec": aec,
        ]
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        else { return nil }
        return String(data: data, encoding: .utf8)
    }
}
