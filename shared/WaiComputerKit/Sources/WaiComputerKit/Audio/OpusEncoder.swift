import Foundation
import AVFoundation

/// Opus encoder for audio compression
/// Note: This is a placeholder that outputs raw PCM data.
/// For production, integrate with libopus via a C wrapper or use AVAudioConverter.
public final class OpusEncoder: @unchecked Sendable {
    public let sampleRate: Int
    public let channels: Int
    public let bitrate: Int

    public init(sampleRate: Int = 16000, channels: Int = 1, bitrate: Int = 24000) {
        self.sampleRate = sampleRate
        self.channels = channels
        self.bitrate = bitrate
    }

    /// Encode PCM audio buffer to compressed format
    /// Returns the audio data suitable for transmission
    public func encode(_ buffer: AVAudioPCMBuffer) -> Data? {
        guard let floatData = buffer.floatChannelData else { return nil }

        let frameLength = Int(buffer.frameLength)
        let channelData = floatData[0]

        // Convert float samples to 16-bit PCM
        var pcmData = Data(capacity: frameLength * 2)

        for i in 0..<frameLength {
            let sample = max(-1.0, min(1.0, channelData[i]))
            let intSample = Int16(sample * 32767)
            withUnsafeBytes(of: intSample.littleEndian) { bytes in
                pcmData.append(contentsOf: bytes)
            }
        }

        // In production, this would use libopus to compress the PCM data
        // For now, return PCM data which the backend can handle
        return pcmData
    }

    /// Encode raw PCM data
    public func encode(_ pcmData: Data) -> Data? {
        // Passthrough for now - would be Opus-encoded in production
        return pcmData
    }
}

/// Opus decoder for audio decompression
public final class OpusDecoder: @unchecked Sendable {
    public let sampleRate: Int
    public let channels: Int

    public init(sampleRate: Int = 16000, channels: Int = 1) {
        self.sampleRate = sampleRate
        self.channels = channels
    }

    /// Decode compressed audio to PCM buffer
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
