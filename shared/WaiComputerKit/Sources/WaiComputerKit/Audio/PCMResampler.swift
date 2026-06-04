import Foundation
import AVFoundation

/// Thin wrapper around `AVAudioConverter` for resampling native capture audio
/// to provider-configured Float32 PCM. Realtime STT uses the target rate
/// supplied by the caller instead of a hard-coded recording-upload format.
///
/// **Why not arithmetic decimation?** The previous implementation averaged
/// adjacent samples (44.1/48 kHz → 16 kHz). That is a low-pass-free averaging
/// filter and aliases high-frequency content — most painful on Russian where
/// fricative consonants (Щ, Ч, Ц, Ш) carry energy in the 4–8 kHz band that
/// gets folded back into the audible range as garbage. AVAudioConverter
/// applies proper anti-aliasing (mastering-quality FIR by default) so the
/// resampled signal is a faithful representation of the band-limited input.
public final class PCMResampler: @unchecked Sendable {
    private let target: AVAudioFormat
    private let converter: AVAudioConverter
    private let lock = NSLock()
    public let sourceFormat: AVAudioFormat

    public init?(
        source: AVAudioFormat,
        targetSampleRate: Double = 16_000,
        targetChannelCount: AVAudioChannelCount = 1
    ) {
        guard let target = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: targetSampleRate,
            channels: targetChannelCount,
            interleaved: false
        ) else { return nil }
        guard let converter = AVAudioConverter(from: source, to: target) else { return nil }
        // Mastering quality FIR — small CPU cost, big quality win on Russian.
        converter.sampleRateConverterQuality = AVAudioQuality.max.rawValue
        self.target = target
        self.converter = converter
        self.sourceFormat = source
    }

    /// Convert a single input buffer. Returns the resampled buffer or `nil`
    /// when the input was empty / converter signalled an error.
    public func convert(_ input: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        let inFrames = input.frameLength
        guard inFrames > 0 else { return nil }

        let ratio = target.sampleRate / sourceFormat.sampleRate
        let estOut = AVAudioFrameCount((Double(inFrames) * ratio).rounded(.up)) + 32
        guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: estOut) else {
            return nil
        }

        var error: NSError?
        var supplied = false
        lock.lock()
        defer { lock.unlock() }
        converter.reset()
        let status = converter.convert(to: out, error: &error) { _, status in
            if supplied {
                status.pointee = .endOfStream
                return nil
            }
            supplied = true
            status.pointee = .haveData
            return input
        }

        if status == .error || error != nil {
            return nil
        }
        return out
    }
}
