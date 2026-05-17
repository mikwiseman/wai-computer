import Foundation
import AVFoundation

/// Thin wrapper around `AVAudioConverter` for downsampling native mic audio
/// to 16 kHz mono Float32 (Inworld + ElevenLabs both consume LINEAR16 / PCM16
/// at 16 kHz; we keep the intermediate Float32 here and convert to Int16 in
/// the encoder).
///
/// **Why not arithmetic decimation?** The previous implementation averaged
/// adjacent samples (44.1/48 kHz → 16 kHz). That is a low-pass-free averaging
/// filter and aliases high-frequency content — most painful on Russian where
/// fricative consonants (Щ, Ч, Ц, Ш) carry energy in the 4–8 kHz band that
/// gets folded back into the audible range as garbage. AVAudioConverter
/// applies proper anti-aliasing (mastering-quality FIR by default) so the
/// resampled signal is a faithful representation of the band-limited input.
public final class PCMResampler: @unchecked Sendable {
    private let converter: AVAudioConverter
    private let target: AVAudioFormat
    public let sourceFormat: AVAudioFormat

    public init?(source: AVAudioFormat, targetSampleRate: Double = 16_000) {
        guard let target = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: targetSampleRate,
            channels: 1,
            interleaved: false
        ) else { return nil }
        guard let conv = AVAudioConverter(from: source, to: target) else { return nil }
        // Mastering quality FIR — small CPU cost, big quality win on Russian.
        conv.sampleRateConverterQuality = AVAudioQuality.max.rawValue
        self.converter = conv
        self.target = target
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
