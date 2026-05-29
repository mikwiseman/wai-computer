import AVFoundation
import XCTest
@testable import WaiComputerKit

final class AudioCompressorTests: XCTestCase {

    private var tempDir: URL!

    override func setUpWithError() throws {
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("AudioCompressorTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tempDir)
    }

    private func tempURL(_ name: String) -> URL {
        tempDir.appendingPathComponent(name)
    }

    private func fileSize(_ url: URL) throws -> Int64 {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        return Int64(values.fileSize ?? 0)
    }

    /// Writes a sine-wave PCM WAV via the production AudioFileWriter.
    private func makeSineWAV(
        name: String = "source.wav",
        seconds: Double,
        sampleRate: Int = 16000,
        channels: Int = 1,
        frequency: Double = 440
    ) throws -> URL {
        let url = tempURL(name)
        let writer = try AudioFileWriter(fileURL: url, sampleRate: sampleRate, channels: channels)
        let frames = Int(Double(sampleRate) * seconds)
        var pcm = Data(capacity: frames * 2 * channels)
        for n in 0..<frames {
            let value = sin(2.0 * Double.pi * frequency * Double(n) / Double(sampleRate))
            var sample = Int16(max(-1.0, min(1.0, value)) * 32767.0).littleEndian
            for _ in 0..<channels {
                withUnsafeBytes(of: &sample) { pcm.append(contentsOf: $0) }
            }
        }
        writer.writeEncodedPCM(pcm)
        try writer.finalize()
        return url
    }

    func testCompressMonoWAVProducesSmallerDecodableAAC() throws {
        let source = try makeSineWAV(seconds: 3.0)
        let sourceSize = try fileSize(source)
        let destination = tempURL("out.m4a")

        let result = try AudioCompressor.compressWAVToAAC(
            source: source,
            destination: destination,
            bitRate: 48_000
        )

        XCTAssertTrue(FileManager.default.fileExists(atPath: destination.path))
        let destSize = try fileSize(destination)
        XCTAssertGreaterThan(destSize, 0)
        XCTAssertLessThan(destSize, sourceSize, "AAC must be smaller than raw PCM WAV")
        XCTAssertEqual(result.url, destination)
        XCTAssertEqual(result.byteCount, destSize)

        // Decodable as AAC, mono, correct sample rate
        let decoded = try AVAudioFile(forReading: destination)
        XCTAssertEqual(
            decoded.fileFormat.streamDescription.pointee.mFormatID,
            kAudioFormatMPEG4AAC,
            "container must hold AAC"
        )
        XCTAssertEqual(decoded.fileFormat.channelCount, 1)
        XCTAssertEqual(decoded.fileFormat.sampleRate, 16000, accuracy: 1)

        // Duration preserved within AAC priming/padding tolerance
        let decodedDuration = Double(decoded.length) / decoded.fileFormat.sampleRate
        XCTAssertEqual(decodedDuration, 3.0, accuracy: 0.3)
        XCTAssertEqual(result.durationSeconds, 3.0, accuracy: 0.05)
    }

    func testCompressPreservesSourceChannelCount() throws {
        // macOS can produce a multichannel WAV (mic + system not mixed to mono).
        let source = try makeSineWAV(name: "stereo.wav", seconds: 1.5, channels: 2)
        let destination = tempURL("stereo.m4a")

        let result = try AudioCompressor.compressWAVToAAC(source: source, destination: destination)

        let decoded = try AVAudioFile(forReading: destination)
        XCTAssertEqual(decoded.fileFormat.channelCount, 2, "stereo source stays stereo")
        XCTAssertEqual(decoded.fileFormat.sampleRate, 16000, accuracy: 1)
        XCTAssertGreaterThan(result.byteCount, 0)
    }

    func testCompressOverwritesStaleDestination() throws {
        let source = try makeSineWAV(seconds: 1.0)
        let destination = tempURL("out.m4a")
        try Data(repeating: 0xFF, count: 1024).write(to: destination)

        let result = try AudioCompressor.compressWAVToAAC(source: source, destination: destination)

        // The decodable result replaced the junk bytes.
        let decoded = try AVAudioFile(forReading: destination)
        XCTAssertEqual(decoded.fileFormat.streamDescription.pointee.mFormatID, kAudioFormatMPEG4AAC)
        XCTAssertEqual(result.byteCount, try fileSize(destination))
    }

    func testEmptySourceThrows() throws {
        let url = tempURL("empty.wav")
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        try writer.finalize() // header only, zero frames

        XCTAssertThrowsError(
            try AudioCompressor.compressWAVToAAC(source: url, destination: tempURL("empty.m4a"))
        )
    }
}
