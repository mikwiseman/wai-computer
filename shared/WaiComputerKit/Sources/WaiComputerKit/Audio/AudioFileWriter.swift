import Foundation
import os
import Sentry

/// Writes a WAV file incrementally during recording.
/// Accepts pre-encoded int16 PCM data (the same `Data` returned by `AudioEncoder.encode()`).
public final class AudioFileWriter: @unchecked Sendable {
    public let fileURL: URL
    public let sampleRate: Int
    public let channels: Int
    public private(set) var totalBytesWritten: Int64 = 0

    /// `true` after a write failure (disk full, I/O error). Once set, all
    /// subsequent writes are skipped — the caller should finalize and stop.
    public private(set) var hasWriteFailure = false

    public var durationSeconds: Double {
        let bytesPerSample = 2 * channels
        guard bytesPerSample > 0, sampleRate > 0 else { return 0 }
        return Double(totalBytesWritten) / Double(bytesPerSample) / Double(sampleRate)
    }

    private var fileHandle: FileHandle?
    private var lock = os_unfair_lock()

    /// Creates a new WAV file at the given URL and writes the 44-byte header with placeholder sizes.
    public init(fileURL: URL, sampleRate: Int = 16000, channels: Int = 1) throws {
        self.fileURL = fileURL
        self.sampleRate = sampleRate
        self.channels = channels

        let header = Self.buildWAVHeader(sampleRate: sampleRate, channels: channels, dataSize: 0)
        try header.write(to: fileURL)

        self.fileHandle = try FileHandle(forWritingTo: fileURL)
        self.fileHandle?.seekToEndOfFile()
    }

    /// Appends int16 PCM data to the WAV file. Thread-safe.
    ///
    /// Returns `false` when the write failed (disk full, I/O error) or a
    /// previous write already failed. The caller should stop recording —
    /// subsequent calls are no-ops and the WAV header will be patched with
    /// whatever data made it to disk before the failure.
    @discardableResult
    public func writeEncodedPCM(_ data: Data) -> Bool {
        os_unfair_lock_lock(&lock)
        defer { os_unfair_lock_unlock(&lock) }

        guard !hasWriteFailure, let handle = fileHandle else { return false }

        let offsetBefore = handle.offsetInFile
        handle.write(data)
        let offsetAfter = handle.offsetInFile
        let bytesWritten = offsetAfter - offsetBefore

        if bytesWritten == UInt64(data.count) {
            totalBytesWritten += Int64(data.count)
            return true
        }

        // Partial or failed write — mark as failed to prevent further writes.
        hasWriteFailure = true
        totalBytesWritten += Int64(bytesWritten)
        return false
    }

    /// Patches the RIFF and data subchunk sizes in the WAV header, then closes the file.
    public func finalize() throws {
        os_unfair_lock_lock(&lock)
        defer { os_unfair_lock_unlock(&lock) }

        guard let handle = fileHandle else { return }

        let dataSize = UInt32(totalBytesWritten)
        // RIFF chunk size = total file size - 8 = (44 + dataSize) - 8 = 36 + dataSize
        let riffSize = 36 + dataSize

        // Patch bytes 4-7: RIFF chunk size
        handle.seek(toFileOffset: 4)
        var riffSizeLE = riffSize.littleEndian
        handle.write(Data(bytes: &riffSizeLE, count: 4))

        // Patch bytes 40-43: data subchunk size
        handle.seek(toFileOffset: 40)
        var dataSizeLE = dataSize.littleEndian
        handle.write(Data(bytes: &dataSizeLE, count: 4))

        handle.synchronizeFile()
        handle.closeFile()
        fileHandle = nil

        SentryHelper.addBreadcrumb(
            category: "audio",
            message: "audio file finalized",
            data: ["duration": durationSeconds, "bytes": totalBytesWritten, "hadWriteFailure": hasWriteFailure]
        )
    }

    // MARK: - Private

    private static func buildWAVHeader(sampleRate: Int, channels: Int, dataSize: UInt32) -> Data {
        let bitsPerSample: UInt16 = 16
        let blockAlign = UInt16(channels) * (bitsPerSample / 8)
        let byteRate = UInt32(sampleRate) * UInt32(blockAlign)
        let riffSize: UInt32 = 36 + dataSize

        var header = Data(capacity: 44)

        // RIFF chunk descriptor
        header.append(contentsOf: [0x52, 0x49, 0x46, 0x46]) // "RIFF"
        appendUInt32(&header, riffSize)
        header.append(contentsOf: [0x57, 0x41, 0x56, 0x45]) // "WAVE"

        // fmt subchunk
        header.append(contentsOf: [0x66, 0x6D, 0x74, 0x20]) // "fmt "
        appendUInt32(&header, 16)                             // Subchunk1Size (PCM = 16)
        appendUInt16(&header, 1)                              // AudioFormat (PCM = 1)
        appendUInt16(&header, UInt16(channels))               // NumChannels
        appendUInt32(&header, UInt32(sampleRate))             // SampleRate
        appendUInt32(&header, byteRate)                       // ByteRate
        appendUInt16(&header, blockAlign)                     // BlockAlign
        appendUInt16(&header, bitsPerSample)                  // BitsPerSample

        // data subchunk
        header.append(contentsOf: [0x64, 0x61, 0x74, 0x61]) // "data"
        appendUInt32(&header, dataSize)                       // Subchunk2Size

        return header
    }

    private static func appendUInt32(_ data: inout Data, _ value: UInt32) {
        var le = value.littleEndian
        data.append(Data(bytes: &le, count: 4))
    }

    private static func appendUInt16(_ data: inout Data, _ value: UInt16) {
        var le = value.littleEndian
        data.append(Data(bytes: &le, count: 2))
    }
}
