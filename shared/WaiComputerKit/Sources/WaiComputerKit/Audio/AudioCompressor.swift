import AVFoundation
import Foundation
import os

/// Transcodes the finalized PCM WAV recording to a compressed container before
/// upload. Raw 16 kHz mono PCM is ~110 MB/hour and trips the 200 MB upload
/// ceiling for recordings over ~1h49m; AAC-LC at speech bitrates is ~22 MB/hour.
public enum AudioCompressor {

    public struct CompressedAudio: Sendable {
        public let url: URL
        public let byteCount: Int64
        public let durationSeconds: Double
    }

    public enum CompressionError: Error {
        case emptySource
        case bufferAllocationFailed
    }

    private static let log = Logger(subsystem: "is.waiwai.computer", category: "audio")

    /// Transcodes a PCM WAV file to AAC-LC in an `.m4a` container, preserving the
    /// source sample rate and channel count. Overwrites `destination` if present.
    ///
    /// - Parameter bitRate: target AAC bitrate (per the channel layout). 48 kbps
    ///   mono is high-quality for speech and keeps a 4-hour meeting near ~85 MB.
    @discardableResult
    public static func compressWAVToAAC(
        source: URL,
        destination: URL,
        bitRate: Int = 48_000
    ) throws -> CompressedAudio {
        let input = try AVAudioFile(forReading: source)
        guard input.length > 0 else { throw CompressionError.emptySource }

        let sampleRate = input.fileFormat.sampleRate
        let channelCount = input.fileFormat.channelCount

        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: sampleRate,
            AVNumberOfChannelsKey: Int(channelCount),
            AVEncoderBitRateKey: bitRate,
        ]

        // Start from a clean slate so a partial file from a previous attempt
        // can't corrupt the output.
        try? FileManager.default.removeItem(at: destination)

        let output = try AVAudioFile(forWriting: destination, settings: settings)

        // input.processingFormat == output.processingFormat (standard float32,
        // same sample rate + channels), so one buffer round-trips read → write.
        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: input.processingFormat,
            frameCapacity: 16_384
        ) else {
            throw CompressionError.bufferAllocationFailed
        }

        while input.framePosition < input.length {
            try input.read(into: buffer)
            if buffer.frameLength == 0 { break }
            try output.write(from: buffer)
        }

        let byteCount = (try? destination.resourceValues(forKeys: [.fileSizeKey]).fileSize)
            .map(Int64.init) ?? 0
        let durationSeconds = Double(input.length) / sampleRate

        log.info(
            "Compressed WAV→AAC frames=\(input.length, privacy: .public) bytes=\(byteCount, privacy: .public)"
        )

        return CompressedAudio(url: destination, byteCount: byteCount, durationSeconds: durationSeconds)
    }
}
