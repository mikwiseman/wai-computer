import AVFoundation
import Foundation

struct CaptureAudioProcessingStats: Equatable, Sendable {
    var buffersReceived = 0
    var buffersYielded = 0
    var emptyBuffers = 0
    var missingFloatData = 0
    var allocationFailures = 0
    var resamplerBuildFailures = 0
    var conversionFailures = 0
    var resamplerRebuilds = 0
    var passthroughCopies = 0

    var hasFailures: Bool {
        emptyBuffers > 0 ||
            missingFloatData > 0 ||
            allocationFailures > 0 ||
            resamplerBuildFailures > 0 ||
            conversionFailures > 0
    }
}

final class CaptureAudioProcessor: @unchecked Sendable {
    private let targetFormat: AVAudioFormat
    private var resampler: PCMResampler?
    private var resamplerSourceFormat: AVAudioFormat?
    private var stats = CaptureAudioProcessingStats()

    init?(config: AudioCaptureConfig) {
        guard let targetFormat = config.format else { return nil }
        self.targetFormat = targetFormat
    }

    var snapshot: CaptureAudioProcessingStats {
        stats
    }

    func reset() {
        resampler = nil
        resamplerSourceFormat = nil
        stats = CaptureAudioProcessingStats()
    }

    func process(_ input: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        stats.buffersReceived += 1

        guard input.frameLength > 0 else {
            stats.emptyBuffers += 1
            return nil
        }
        guard input.floatChannelData != nil else {
            stats.missingFloatData += 1
            return nil
        }

        if format(input.format, matches: targetFormat) {
            guard let copy = copyBuffer(input, format: targetFormat) else {
                stats.allocationFailures += 1
                return nil
            }
            stats.passthroughCopies += 1
            stats.buffersYielded += 1
            return copy
        }

        if resampler == nil || !format(input.format, matches: resamplerSourceFormat) {
            guard let newResampler = PCMResampler(
                source: input.format,
                targetSampleRate: targetFormat.sampleRate,
                targetChannelCount: targetFormat.channelCount
            ) else {
                stats.resamplerBuildFailures += 1
                return nil
            }
            resampler = newResampler
            resamplerSourceFormat = input.format
            stats.resamplerRebuilds += 1
        }

        guard let converted = resampler?.convert(input) else {
            stats.conversionFailures += 1
            return nil
        }
        stats.buffersYielded += 1
        return converted
    }

    private func copyBuffer(
        _ input: AVAudioPCMBuffer,
        format: AVAudioFormat
    ) -> AVAudioPCMBuffer? {
        guard let output = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: input.frameLength
        ) else { return nil }
        output.frameLength = input.frameLength

        guard let source = input.floatChannelData,
              let destination = output.floatChannelData else {
            return nil
        }

        let channels = min(Int(input.format.channelCount), Int(format.channelCount))
        let frames = Int(input.frameLength)
        for channel in 0..<channels {
            destination[channel].update(from: source[channel], count: frames)
        }
        return output
    }

    private func format(_ lhs: AVAudioFormat, matches rhs: AVAudioFormat?) -> Bool {
        guard let rhs else { return false }
        return format(lhs, matches: rhs)
    }

    private func format(_ lhs: AVAudioFormat, matches rhs: AVAudioFormat) -> Bool {
        lhs.commonFormat == rhs.commonFormat &&
            lhs.sampleRate == rhs.sampleRate &&
            lhs.channelCount == rhs.channelCount &&
            lhs.isInterleaved == rhs.isInterleaved
    }
}
