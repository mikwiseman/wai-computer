import AVFoundation
import Foundation

/// Encodes captured Float32 PCM buffers to the provider session's declared
/// LINEAR16 sample rate. This lets dictation start capture before the backend
/// has returned the exact provider route, then normalize once routing is known.
public final class RealtimePCMEncoder: @unchecked Sendable {
    private let targetSampleRate: Double
    private let channels: Int
    private var resampler: PCMResampler?
    private var resamplerSourceFormat: AVAudioFormat?

    public init(targetSampleRate: Int, channels: Int) {
        self.targetSampleRate = Double(targetSampleRate)
        self.channels = channels
    }

    public func encode(_ buffer: AVAudioPCMBuffer) -> Data? {
        guard channels == 1 else {
            return AudioEncoder(sampleRate: Int(targetSampleRate), channels: channels).encode(buffer)
        }

        let needsResample = abs(buffer.format.sampleRate - targetSampleRate) > 0.5
            || buffer.format.channelCount != 1
        guard needsResample else {
            return AudioEncoder(sampleRate: Int(targetSampleRate), channels: channels).encode(buffer)
        }

        if !Self.sameFormat(resamplerSourceFormat, buffer.format) {
            resampler = PCMResampler(source: buffer.format, targetSampleRate: targetSampleRate)
            resamplerSourceFormat = buffer.format
        }
        guard let converted = resampler?.convert(buffer) else { return nil }
        return AudioEncoder(sampleRate: Int(targetSampleRate), channels: channels).encode(converted)
    }

    private static func sameFormat(_ lhs: AVAudioFormat?, _ rhs: AVAudioFormat) -> Bool {
        guard let lhs else { return false }
        return abs(lhs.sampleRate - rhs.sampleRate) < 0.5
            && lhs.channelCount == rhs.channelCount
            && lhs.commonFormat == rhs.commonFormat
            && lhs.isInterleaved == rhs.isInterleaved
    }
}
