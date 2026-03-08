import Foundation
import AVFoundation

/// Audio encoder that converts PCM buffers to 16-bit PCM data for transmission.
/// The backend expects raw linear16 PCM at 16kHz.
public final class AudioEncoder: @unchecked Sendable {
    public let sampleRate: Int
    public let channels: Int
    public let bitrate: Int

    public init(sampleRate: Int = 16000, channels: Int = 1, bitrate: Int = 24000) {
        self.sampleRate = sampleRate
        self.channels = channels
        self.bitrate = bitrate
    }

    /// Encode PCM audio buffer to 16-bit linear PCM data.
    /// Handles both mono (non-interleaved) and multichannel (interleaved) buffers.
    public func encode(_ buffer: AVAudioPCMBuffer) -> Data? {
        guard let floatData = buffer.floatChannelData else { return nil }

        let frameLength = Int(buffer.frameLength)
        let isInterleaved = buffer.format.isInterleaved
        let bufferChannels = Int(buffer.format.channelCount)

        if isInterleaved && bufferChannels > 1 {
            // Interleaved: samples are [L0, R0, L1, R1, ...] all in floatData[0]
            let totalSamples = frameLength * bufferChannels
            var pcmData = Data(capacity: totalSamples * 2)
            let src = floatData[0]
            for i in 0..<totalSamples {
                let sample = max(-1.0, min(1.0, src[i]))
                let intSample = Int16(sample * 32767)
                withUnsafeBytes(of: intSample.littleEndian) { bytes in
                    pcmData.append(contentsOf: bytes)
                }
            }
            return pcmData
        } else {
            // Non-interleaved mono: just channel 0
            let channelData = floatData[0]
            var pcmData = Data(capacity: frameLength * 2)
            for i in 0..<frameLength {
                let sample = max(-1.0, min(1.0, channelData[i]))
                let intSample = Int16(sample * 32767)
                withUnsafeBytes(of: intSample.littleEndian) { bytes in
                    pcmData.append(contentsOf: bytes)
                }
            }
            return pcmData
        }
    }

    /// Encode raw PCM data (passthrough)
    public func encode(_ pcmData: Data) -> Data? {
        return pcmData
    }
}

/// Audio decoder that converts 16-bit PCM data back to float PCM buffers
public final class AudioDecoder: @unchecked Sendable {
    public let sampleRate: Int
    public let channels: Int

    public init(sampleRate: Int = 16000, channels: Int = 1) {
        self.sampleRate = sampleRate
        self.channels = channels
    }

    /// Decode 16-bit PCM data to float PCM buffer
    public func decode(_ data: Data) -> AVAudioPCMBuffer? {
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: Double(sampleRate),
            channels: AVAudioChannelCount(channels),
            interleaved: false
        ) else { return nil }

        let frameCount = data.count / 2  // 16-bit samples
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frameCount)) else {
            return nil
        }

        buffer.frameLength = AVAudioFrameCount(frameCount)

        guard let floatData = buffer.floatChannelData else { return nil }

        data.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)
            for i in 0..<frameCount {
                let sample = Float(int16Ptr[i]) / 32767.0
                floatData[0][i] = sample
            }
        }

        return buffer
    }
}

// Backwards compatibility typealiases
@available(*, deprecated, renamed: "AudioEncoder")
public typealias OpusEncoder = AudioEncoder
@available(*, deprecated, renamed: "AudioDecoder")
public typealias OpusDecoder = AudioDecoder
