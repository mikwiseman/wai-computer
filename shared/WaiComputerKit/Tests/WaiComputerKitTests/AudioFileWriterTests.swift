import XCTest
@testable import WaiComputerKit

final class AudioFileWriterTests: XCTestCase {

    private var tempDir: URL!

    override func setUpWithError() throws {
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("AudioFileWriterTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tempDir)
    }

    private func tempURL(_ name: String = "test.wav") -> URL {
        tempDir.appendingPathComponent(name)
    }

    // MARK: - Init writes a valid 44-byte WAV header

    func testInitWritesFortyFourByteHeader() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        defer { try? writer.finalize() }

        let data = try Data(contentsOf: url)
        XCTAssertEqual(data.count, 44, "WAV header must be exactly 44 bytes before any PCM is written")
    }

    func testHeaderMagicBytes() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        defer { try? writer.finalize() }

        let header = try Data(contentsOf: url)

        XCTAssertEqual(Array(header[0..<4]), [0x52, 0x49, 0x46, 0x46], "RIFF magic")
        XCTAssertEqual(Array(header[8..<12]), [0x57, 0x41, 0x56, 0x45], "WAVE magic")
        XCTAssertEqual(Array(header[12..<16]), [0x66, 0x6D, 0x74, 0x20], "'fmt ' magic")
        XCTAssertEqual(Array(header[36..<40]), [0x64, 0x61, 0x74, 0x61], "'data' magic")
    }

    func testHeaderFormatFields() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        defer { try? writer.finalize() }

        let header = try Data(contentsOf: url)

        // fmt subchunk size at offset 16 = 16 (PCM)
        XCTAssertEqual(readUInt32LE(header, offset: 16), 16)
        // AudioFormat at offset 20 = 1 (PCM)
        XCTAssertEqual(readUInt16LE(header, offset: 20), 1)
        // NumChannels at offset 22 = 1
        XCTAssertEqual(readUInt16LE(header, offset: 22), 1)
        // SampleRate at offset 24 = 16000
        XCTAssertEqual(readUInt32LE(header, offset: 24), 16000)
        // BitsPerSample at offset 34 = 16
        XCTAssertEqual(readUInt16LE(header, offset: 34), 16)
        // ByteRate at offset 28 = sampleRate * channels * bytesPerSample = 16000 * 1 * 2 = 32000
        XCTAssertEqual(readUInt32LE(header, offset: 28), 32000)
        // BlockAlign at offset 32 = channels * bytesPerSample = 1 * 2 = 2
        XCTAssertEqual(readUInt16LE(header, offset: 32), 2)
    }

    func testStereoHeader() throws {
        let url = tempURL("stereo.wav")
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 48000, channels: 2)
        defer { try? writer.finalize() }

        let header = try Data(contentsOf: url)

        XCTAssertEqual(readUInt16LE(header, offset: 22), 2, "channels=2")
        XCTAssertEqual(readUInt32LE(header, offset: 24), 48000, "sampleRate=48000")
        XCTAssertEqual(readUInt32LE(header, offset: 28), 48000 * 2 * 2, "byteRate=sampleRate*channels*2")
        XCTAssertEqual(readUInt16LE(header, offset: 32), 4, "blockAlign=channels*2")
    }

    func testInitialDataSizeIsZero() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        defer { try? writer.finalize() }

        let header = try Data(contentsOf: url)
        XCTAssertEqual(readUInt32LE(header, offset: 40), 0, "data subchunk size starts at 0")
    }

    // MARK: - writeEncodedPCM

    func testWriteAppendsAndIncrementsCounter() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)

        let payload = Data(repeating: 0xAB, count: 100)
        writer.writeEncodedPCM(payload)

        XCTAssertEqual(writer.totalBytesWritten, 100)

        let second = Data(repeating: 0xCD, count: 50)
        writer.writeEncodedPCM(second)

        XCTAssertEqual(writer.totalBytesWritten, 150)

        try writer.finalize()

        let onDisk = try Data(contentsOf: url)
        XCTAssertEqual(onDisk.count, 44 + 150, "header + 150 bytes of PCM")
        XCTAssertEqual(Array(onDisk[44..<144]), Array(repeating: 0xAB, count: 100))
        XCTAssertEqual(Array(onDisk[144..<194]), Array(repeating: 0xCD, count: 50))
    }

    // MARK: - finalize patches sizes

    func testFinalizePatchesRiffAndDataSizes() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        writer.writeEncodedPCM(Data(repeating: 0x10, count: 200))
        try writer.finalize()

        let onDisk = try Data(contentsOf: url)
        // RIFF chunk size at offset 4 = 36 + dataSize
        XCTAssertEqual(readUInt32LE(onDisk, offset: 4), 36 + 200)
        // data subchunk size at offset 40 = dataSize
        XCTAssertEqual(readUInt32LE(onDisk, offset: 40), 200)
    }

    func testFinalizeWithNoDataWritesValidHeader() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        try writer.finalize()

        let onDisk = try Data(contentsOf: url)
        XCTAssertEqual(onDisk.count, 44)
        XCTAssertEqual(readUInt32LE(onDisk, offset: 4), 36, "riffSize=36 when dataSize=0")
        XCTAssertEqual(readUInt32LE(onDisk, offset: 40), 0, "dataSize=0")
    }

    func testFinalizeIsIdempotent() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        writer.writeEncodedPCM(Data(repeating: 0x42, count: 8))
        try writer.finalize()
        // Second finalize should be a no-op (fileHandle = nil) and not throw
        try writer.finalize()

        let onDisk = try Data(contentsOf: url)
        XCTAssertEqual(onDisk.count, 44 + 8)
        XCTAssertEqual(readUInt32LE(onDisk, offset: 40), 8)
    }

    func testWriteAfterFinalizeIsNoOp() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        writer.writeEncodedPCM(Data(repeating: 0x01, count: 10))
        try writer.finalize()

        let before = writer.totalBytesWritten
        writer.writeEncodedPCM(Data(repeating: 0x99, count: 100))
        XCTAssertEqual(writer.totalBytesWritten, before, "write after finalize must be a no-op")

        let onDisk = try Data(contentsOf: url)
        XCTAssertEqual(onDisk.count, 44 + 10, "file size unchanged after no-op write")
    }

    // MARK: - durationSeconds

    func testDurationCalculationMono() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        defer { try? writer.finalize() }

        // 1 second @ 16kHz mono int16 = 32000 bytes
        writer.writeEncodedPCM(Data(count: 32000))
        XCTAssertEqual(writer.durationSeconds, 1.0, accuracy: 1e-6)

        writer.writeEncodedPCM(Data(count: 16000))
        XCTAssertEqual(writer.durationSeconds, 1.5, accuracy: 1e-6)
    }

    func testDurationCalculationStereo() throws {
        let url = tempURL("stereo.wav")
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 48000, channels: 2)
        defer { try? writer.finalize() }

        // 0.5 second @ 48kHz stereo int16 = 48000 * 2 * 2 * 0.5 = 96000 bytes
        writer.writeEncodedPCM(Data(count: 96000))
        XCTAssertEqual(writer.durationSeconds, 0.5, accuracy: 1e-6)
    }

    func testDurationZeroWhenEmpty() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        defer { try? writer.finalize() }
        XCTAssertEqual(writer.durationSeconds, 0.0)
    }

    // MARK: - Thread safety

    func testConcurrentWritesDoNotCorruptCounter() throws {
        let url = tempURL()
        let writer = try AudioFileWriter(fileURL: url, sampleRate: 16000, channels: 1)
        let writers = 8
        let perWriter = 100
        let payload = Data(repeating: 0xEE, count: 16)

        let group = DispatchGroup()
        let queue = DispatchQueue.global()
        for _ in 0..<writers {
            group.enter()
            queue.async {
                for _ in 0..<perWriter {
                    writer.writeEncodedPCM(payload)
                }
                group.leave()
            }
        }
        group.wait()

        try writer.finalize()
        let expected = Int64(writers * perWriter * payload.count)
        XCTAssertEqual(writer.totalBytesWritten, expected)

        let onDisk = try Data(contentsOf: url)
        XCTAssertEqual(onDisk.count, 44 + Int(expected))
        XCTAssertEqual(readUInt32LE(onDisk, offset: 40), UInt32(expected))
    }

    // MARK: - Helpers

    private func readUInt16LE(_ data: Data, offset: Int) -> UInt16 {
        let bytes = data[offset..<(offset + 2)]
        return bytes.withUnsafeBytes { $0.load(as: UInt16.self).littleEndian }
    }

    private func readUInt32LE(_ data: Data, offset: Int) -> UInt32 {
        let bytes = data[offset..<(offset + 4)]
        return bytes.withUnsafeBytes { $0.load(as: UInt32.self).littleEndian }
    }
}
