import AVFoundation
import XCTest

@testable import WaiComputerKit

final class MediaImportSupportTests: XCTestCase {

    func testVideoExtensionPolicy() {
        XCTAssertTrue(MediaImportSupport.isVideoExtension("mp4"))
        XCTAssertTrue(MediaImportSupport.isVideoExtension("MOV"))
        XCTAssertTrue(MediaImportSupport.isVideoExtension("mkv"))
        XCTAssertFalse(MediaImportSupport.isVideoExtension("mp3"))
        XCTAssertFalse(MediaImportSupport.isVideoExtension("m4a"))
        // webm imports as audio by default; the server resolves by content.
        XCTAssertFalse(MediaImportSupport.isVideoExtension("webm"))
    }

    func testImportableExtensionsCoverLegacyAudioList() {
        // The pre-video picker list must stay importable — no regressions.
        for ext in ["mp3", "wav", "m4a", "ogg", "webm", "opus", "flac"] {
            XCTAssertTrue(
                MediaImportSupport.importableExtensions.contains(ext),
                "\(ext) missing from importable extensions"
            )
        }
        for ext in ["mp4", "mov", "mkv", "avi"] {
            XCTAssertTrue(
                MediaImportSupport.importableExtensions.contains(ext),
                "\(ext) missing from importable extensions"
            )
        }
    }

    func testMimeTypesMatchBackendTable() {
        // Mirrors backend EXTENSION_TO_CONTENT_TYPE so resolve_import_extension
        // round-trips on the server.
        XCTAssertEqual(MediaImportSupport.mimeType(forExtension: "mp3"), "audio/mpeg")
        XCTAssertEqual(MediaImportSupport.mimeType(forExtension: "m4a"), "audio/mp4")
        XCTAssertEqual(MediaImportSupport.mimeType(forExtension: "mp4"), "video/mp4")
        XCTAssertEqual(MediaImportSupport.mimeType(forExtension: "MOV"), "video/quicktime")
        XCTAssertEqual(MediaImportSupport.mimeType(forExtension: "mkv"), "video/x-matroska")
        XCTAssertEqual(MediaImportSupport.mimeType(forExtension: "avi"), "video/x-msvideo")
        XCTAssertEqual(MediaImportSupport.mimeType(forExtension: "xyz"), "application/octet-stream")
    }

    func testExtractAudioForUploadFromRealVideo() async throws {
        // Synthesize a 1-second mp4 (video + tone audio) with AVFoundation, then
        // extract the audio track the way the import flow does.
        let source = FileManager.default.temporaryDirectory
            .appendingPathComponent("media-import-test-\(UUID().uuidString).mp4")
        defer { try? FileManager.default.removeItem(at: source) }
        try Self.writeTestVideo(to: source)

        guard let extracted = await MediaAudioExtractor.extractAudioForUpload(source: source) else {
            XCTFail("expected local audio extraction to succeed for mp4")
            return
        }
        defer { try? FileManager.default.removeItem(at: extracted) }

        XCTAssertEqual(extracted.pathExtension, "m4a")
        let size = (try? extracted.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        XCTAssertGreaterThan(size, 0)
        let audioFile = try AVAudioFile(forReading: extracted)
        XCTAssertGreaterThan(audioFile.length, 0)
    }

    func testExtractAudioForUploadReturnsNilForGarbage() async throws {
        let source = FileManager.default.temporaryDirectory
            .appendingPathComponent("media-import-garbage-\(UUID().uuidString).mp4")
        defer { try? FileManager.default.removeItem(at: source) }
        try Data("not a real video".utf8).write(to: source)

        let extracted = await MediaAudioExtractor.extractAudioForUpload(source: source)
        XCTAssertNil(extracted)
    }

    /// Writes a minimal 1-second mp4 with a silent-ish PCM audio track using
    /// AVAssetWriter (no external tools needed in CI).
    private static func writeTestVideo(to url: URL) throws {
        let writer = try AVAssetWriter(outputURL: url, fileType: .mp4)

        let videoSettings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: 320,
            AVVideoHeightKey: 240,
        ]
        let videoInput = AVAssetWriterInput(mediaType: .video, outputSettings: videoSettings)
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: videoInput,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
                kCVPixelBufferWidthKey as String: 320,
                kCVPixelBufferHeightKey as String: 240,
            ]
        )
        writer.add(videoInput)

        var audioLayout = AudioChannelLayout()
        audioLayout.mChannelLayoutTag = kAudioChannelLayoutTag_Mono
        let audioSettings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVEncoderBitRateKey: 32_000,
            AVChannelLayoutKey: Data(bytes: &audioLayout, count: MemoryLayout<AudioChannelLayout>.size),
        ]
        let audioInput = AVAssetWriterInput(mediaType: .audio, outputSettings: audioSettings)
        writer.add(audioInput)

        guard writer.startWriting() else {
            throw writer.error ?? NSError(domain: "test", code: 1)
        }
        writer.startSession(atSourceTime: .zero)

        // 10 video frames over 1 second.
        var pixelBuffer: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &pixelBuffer)
        for frame in 0..<10 {
            while !videoInput.isReadyForMoreMediaData {
                Thread.sleep(forTimeInterval: 0.01)
            }
            if let buffer = pixelBuffer {
                adaptor.append(buffer, withPresentationTime: CMTime(value: CMTimeValue(frame), timescale: 10))
            }
        }
        videoInput.markAsFinished()

        // 1 second of 440 Hz tone as PCM buffers via a format converter-free path:
        // append raw PCM through a CMSampleBuffer.
        let sampleRate = 16_000
        let frameCount = sampleRate
        var samples = [Int16](repeating: 0, count: frameCount)
        for index in 0..<frameCount {
            samples[index] = Int16(8_000 * sin(2.0 * .pi * 440.0 * Double(index) / Double(sampleRate)))
        }
        var asbd = AudioStreamBasicDescription(
            mSampleRate: Float64(sampleRate),
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked,
            mBytesPerPacket: 2,
            mFramesPerPacket: 1,
            mBytesPerFrame: 2,
            mChannelsPerFrame: 1,
            mBitsPerChannel: 16,
            mReserved: 0
        )
        var formatDescription: CMAudioFormatDescription?
        CMAudioFormatDescriptionCreate(
            allocator: nil,
            asbd: &asbd,
            layoutSize: 0,
            layout: nil,
            magicCookieSize: 0,
            magicCookie: nil,
            extensions: nil,
            formatDescriptionOut: &formatDescription
        )
        var blockBuffer: CMBlockBuffer?
        let dataLength = frameCount * 2
        CMBlockBufferCreateWithMemoryBlock(
            allocator: nil,
            memoryBlock: nil,
            blockLength: dataLength,
            blockAllocator: nil,
            customBlockSource: nil,
            offsetToData: 0,
            dataLength: dataLength,
            flags: 0,
            blockBufferOut: &blockBuffer
        )
        samples.withUnsafeBytes { raw in
            _ = CMBlockBufferReplaceDataBytes(
                with: raw.baseAddress!,
                blockBuffer: blockBuffer!,
                offsetIntoDestination: 0,
                dataLength: dataLength
            )
        }
        var sampleBuffer: CMSampleBuffer?
        CMAudioSampleBufferCreateWithPacketDescriptions(
            allocator: nil,
            dataBuffer: blockBuffer!,
            dataReady: true,
            makeDataReadyCallback: nil,
            refcon: nil,
            formatDescription: formatDescription!,
            sampleCount: frameCount,
            presentationTimeStamp: .zero,
            packetDescriptions: nil,
            sampleBufferOut: &sampleBuffer
        )
        while !audioInput.isReadyForMoreMediaData {
            Thread.sleep(forTimeInterval: 0.01)
        }
        audioInput.append(sampleBuffer!)
        audioInput.markAsFinished()

        let done = expectation(description: "writer finished")
        writer.finishWriting {
            done.fulfill()
        }
        _ = XCTWaiter.wait(for: [done], timeout: 30)
        guard writer.status == .completed else {
            throw writer.error ?? NSError(domain: "test", code: 2)
        }
    }

    private static func expectation(description: String) -> XCTestExpectation {
        XCTestExpectation(description: description)
    }
}
