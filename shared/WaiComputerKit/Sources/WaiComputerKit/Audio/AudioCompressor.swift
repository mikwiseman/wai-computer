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

        let temporaryDestination = temporaryOutputURL(for: destination)
        try? FileManager.default.removeItem(at: temporaryDestination)
        defer { try? FileManager.default.removeItem(at: temporaryDestination) }

        do {
            let output = try AVAudioFile(forWriting: temporaryDestination, settings: settings)

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
        }

        try? FileManager.default.removeItem(at: destination)
        try FileManager.default.moveItem(at: temporaryDestination, to: destination)

        let byteCount = (try? destination.resourceValues(forKeys: [.fileSizeKey]).fileSize)
            .map(Int64.init) ?? 0
        let durationSeconds = Double(input.length) / sampleRate

        log.info(
            "Compressed WAV→AAC frames=\(input.length, privacy: .public) bytes=\(byteCount, privacy: .public)"
        )

        return CompressedAudio(url: destination, byteCount: byteCount, durationSeconds: durationSeconds)
    }

    public static func validateCompressedAudio(source: URL, candidate: URL) -> Bool {
        let candidateSize = (try? candidate.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        guard candidateSize > 0 else { return false }

        do {
            let sourceFile = try AVAudioFile(forReading: source)
            let candidateFile = try AVAudioFile(forReading: candidate)
            guard sourceFile.length > 0, candidateFile.length > 0 else { return false }

            let sourceDuration = Double(sourceFile.length) / sourceFile.fileFormat.sampleRate
            let candidateDuration = Double(candidateFile.length) / candidateFile.fileFormat.sampleRate
            let tolerance = max(0.5, sourceDuration * 0.05)
            return abs(sourceDuration - candidateDuration) <= tolerance
        } catch {
            return false
        }
    }

    private static func temporaryOutputURL(for destination: URL) -> URL {
        destination
            .deletingLastPathComponent()
            .appendingPathComponent(".\(destination.lastPathComponent).tmp")
    }
}
