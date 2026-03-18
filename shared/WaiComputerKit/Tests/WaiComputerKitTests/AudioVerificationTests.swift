import XCTest
import AVFoundation
@testable import WaiComputerKit

/// Tests for audio capture verification mechanisms:
/// - MockAudioCapture.hasReceivedAudio (mirrors SystemAudioCapture's atomic flag)
/// - AudioCaptureConfig sample rate / format construction
/// - MockAudioCapture.systemAudio() stereo configuration
/// - AudioEncoder (OpusEncoder) with edge-case buffer sizes
final class AudioVerificationTests: XCTestCase {

    // MARK: - hasReceivedAudio Verification

    /// hasReceivedAudio must start false before any buffers are generated.
    func testHasReceivedAudioStartsFalse() {
        let mock = MockAudioCapture.microphone()
        XCTAssertFalse(mock.hasReceivedAudio,
            "hasReceivedAudio should be false before any buffer generation")
    }

    /// After generating a sine-wave buffer (non-zero samples), hasReceivedAudio must flip to true.
    func testHasReceivedAudioBecomesTrueAfterGeneratingBuffer() {
        let mock = MockAudioCapture.microphone(frequency: 440)
        let buffer = mock.generateBuffer()

        XCTAssertNotNil(buffer, "generateBuffer should produce a valid buffer")
        XCTAssertTrue(mock.hasReceivedAudio,
            "hasReceivedAudio should be true after generating a buffer with non-zero samples")
    }

    /// A buffer filled entirely with silence (0.0) should NOT flip hasReceivedAudio.
    func testHasReceivedAudioStaysFalseForSilentBuffer() {
        let mock = MockAudioCapture.microphone()

        // Inject a silent buffer and trigger emit path through startRecording
        guard let silentBuffer = MockAudioCapture.constantBuffer(
            value: 0.0, channelCount: 1, frameCount: 160
        ) else {
            XCTFail("Failed to create silent buffer")
            return
        }

        // Manually call markReceivedIfNonZero indirectly — inject + use generateBuffer(channelCount:)
        // Since generateBuffer() only produces sine waves, directly test with the mock's state:
        // The mock starts with hasReceivedAudio = false and stays false when all samples are zero.
        // We verify this by creating a fresh mock and checking that a zero-frequency sine wave
        // (which would produce all zeros) does not trigger the flag.
        let zeroFreqMock = MockAudioCapture(
            config: AudioCaptureConfig(sampleRate: 16000, channelCount: 1, bufferSize: 160),
            frequency: 0.0  // sin(0) = 0 for all samples when frequency is 0
        )
        let zeroBuffer = zeroFreqMock.generateBuffer()
        XCTAssertNotNil(zeroBuffer, "Should produce a buffer even with 0 Hz frequency")

        // Verify the buffer is actually all zeros
        if let floatData = zeroBuffer?.floatChannelData {
            for i in 0..<Int(zeroBuffer!.frameLength) {
                XCTAssertEqual(floatData[0][i], 0.0, accuracy: 0.0001,
                    "0 Hz sine should produce zero samples")
            }
        }

        XCTAssertFalse(zeroFreqMock.hasReceivedAudio,
            "hasReceivedAudio should remain false when all samples are zero")
    }

    /// hasReceivedAudio should only flip once — subsequent calls to generateBuffer should not reset it.
    func testHasReceivedAudioRemainsTrue() {
        let mock = MockAudioCapture.microphone(frequency: 440)

        _ = mock.generateBuffer()
        XCTAssertTrue(mock.hasReceivedAudio)

        // Generate more buffers — flag stays true
        _ = mock.generateBuffer()
        _ = mock.generateBuffer()
        XCTAssertTrue(mock.hasReceivedAudio,
            "hasReceivedAudio should remain true once set")
    }

    // MARK: - AudioCaptureConfig with Various Sample Rates

    /// Verify AudioCaptureConfig produces valid AVAudioFormat for common sample rates.
    func testAudioCaptureConfigVariousSampleRates() {
        let sampleRates: [Double] = [8000, 16000, 22050, 44100, 48000, 96000]

        for rate in sampleRates {
            let config = AudioCaptureConfig(sampleRate: rate, channelCount: 1, bufferSize: 1024)

            XCTAssertEqual(config.sampleRate, rate, "Sample rate should match")

            let format = config.format
            XCTAssertNotNil(format, "Format should be valid for \(rate) Hz")
            XCTAssertEqual(format?.sampleRate, rate,
                "Format sample rate should be \(rate)")
            XCTAssertEqual(format?.channelCount, 1,
                "Channel count should be 1 for \(rate) Hz config")
            XCTAssertEqual(format?.commonFormat, .pcmFormatFloat32,
                "Common format should be float32 for \(rate) Hz config")
            XCTAssertFalse(format?.isInterleaved ?? true,
                "Format should be non-interleaved for \(rate) Hz config")
        }
    }

    /// Verify that buffer size calculation at different sample rates produces expected durations.
    func testAudioCaptureConfigBufferDurationCalculation() {
        // 160ms buffers at different sample rates
        let cases: [(sampleRate: Double, expectedBufferSize: UInt32)] = [
            (8000, 1280),    // 8kHz * 0.16s
            (16000, 2560),   // 16kHz * 0.16s
            (48000, 7680),   // 48kHz * 0.16s
        ]

        for (rate, expectedSize) in cases {
            let bufferSize = UInt32(rate * 0.16)
            XCTAssertEqual(bufferSize, expectedSize,
                "160ms at \(rate) Hz should be \(expectedSize) samples")

            let config = AudioCaptureConfig(sampleRate: rate, channelCount: 1, bufferSize: bufferSize)
            XCTAssertEqual(config.bufferSize, expectedSize)
        }
    }

    // MARK: - MockAudioCapture.systemAudio() Stereo Config

    /// systemAudio() factory must produce a 2-channel (stereo) 16kHz mock.
    func testSystemAudioFactoryCreatesStereoConfig() {
        let mock = MockAudioCapture.systemAudio()

        XCTAssertEqual(mock.config.channelCount, 2,
            "systemAudio() should produce 2-channel config")
        XCTAssertEqual(mock.config.sampleRate, 16000,
            "systemAudio() should use 16kHz sample rate")
        XCTAssertEqual(mock.config.bufferSize, 2560,
            "systemAudio() should use 2560 buffer size (160ms @ 16kHz)")
    }

    /// systemAudio() buffers must have stereo format with distinct channel data.
    func testSystemAudioBufferHasTwoChannels() {
        let mock = MockAudioCapture.systemAudio(frequency: 440)
        guard let buffer = mock.generateBuffer() else {
            XCTFail("systemAudio mock should generate a valid buffer")
            return
        }

        XCTAssertEqual(buffer.format.channelCount, 2,
            "Buffer from systemAudio() should have 2 channels")
        XCTAssertEqual(buffer.format.sampleRate, 16000)
        XCTAssertFalse(buffer.format.isInterleaved,
            "systemAudio() buffers must be non-interleaved")
        XCTAssertEqual(buffer.frameLength, 2560)

        // Both channels should contain non-zero sine wave data
        guard let floatData = buffer.floatChannelData else {
            XCTFail("No float channel data in stereo buffer")
            return
        }

        var ch0HasAudio = false
        var ch1HasAudio = false
        for i in 0..<Int(buffer.frameLength) {
            if abs(floatData[0][i]) > 0.001 { ch0HasAudio = true }
            if abs(floatData[1][i]) > 0.001 { ch1HasAudio = true }
            if ch0HasAudio && ch1HasAudio { break }
        }
        XCTAssertTrue(ch0HasAudio, "Channel 0 should have non-zero audio")
        XCTAssertTrue(ch1HasAudio, "Channel 1 should have non-zero audio")
    }

    /// systemAudio() should also set hasReceivedAudio after generating a buffer.
    func testSystemAudioSetsHasReceivedAudio() {
        let mock = MockAudioCapture.systemAudio(frequency: 880)
        XCTAssertFalse(mock.hasReceivedAudio)

        _ = mock.generateBuffer()
        XCTAssertTrue(mock.hasReceivedAudio,
            "Stereo generateBuffer should also set hasReceivedAudio")
    }

    // MARK: - AudioEncoder (OpusEncoder) Edge Cases: Very Small Buffers

    /// Encoder should handle the minimum possible frame count (1 frame).
    func testEncoderHandsSingleFrame() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 1)

        guard let buffer = MockAudioCapture.constantBuffer(
            value: 0.5, channelCount: 1, frameCount: 1
        ) else {
            XCTFail("Failed to create 1-frame buffer")
            return
        }

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoder should handle 1-frame buffer")
            return
        }

        // 1 frame * 1 channel * 2 bytes = 2 bytes
        XCTAssertEqual(encoded.count, 2, "1 mono frame should encode to 2 bytes")

        encoded.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)
            let sample = Int16(littleEndian: int16Ptr[0])
            XCTAssertEqual(sample, Int16(0.5 * 32767),
                "Single frame value should encode correctly")
        }
    }

    /// Encoder should handle very small frame counts (2-10 frames) for both mono and stereo.
    func testEncoderHandlesVerySmallBuffers() {
        let monoEncoder = AudioEncoder(sampleRate: 16000, channels: 1)
        let stereoEncoder = AudioEncoder(sampleRate: 16000, channels: 2)

        for frameCount: UInt32 in [2, 5, 10] {
            // Mono
            guard let monoBuffer = MockAudioCapture.constantBuffer(
                value: 0.3, channelCount: 1, frameCount: frameCount
            ) else {
                XCTFail("Failed to create mono buffer with \(frameCount) frames")
                continue
            }

            guard let monoEncoded = monoEncoder.encode(monoBuffer) else {
                XCTFail("Mono encoder failed for \(frameCount) frames")
                continue
            }

            XCTAssertEqual(monoEncoded.count, Int(frameCount) * 2,
                "Mono \(frameCount) frames should produce \(frameCount * 2) bytes")

            // Stereo
            guard let stereoBuffer = MockAudioCapture.multichannelBuffer(
                values: [0.3, 0.7], frameCount: frameCount
            ) else {
                XCTFail("Failed to create stereo buffer with \(frameCount) frames")
                continue
            }

            guard let stereoEncoded = stereoEncoder.encode(stereoBuffer) else {
                XCTFail("Stereo encoder failed for \(frameCount) frames")
                continue
            }

            XCTAssertEqual(stereoEncoded.count, Int(frameCount) * 2 * 2,
                "Stereo \(frameCount) frames should produce \(frameCount * 4) bytes")
        }
    }

    // MARK: - AudioEncoder (OpusEncoder) Edge Cases: Large Buffers

    /// Encoder should handle large buffers (32000+ frames = 2 seconds @ 16kHz).
    func testEncoderHandlesLargeMonoBuffer() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 1)
        let frameCount: UInt32 = 32000

        guard let buffer = MockAudioCapture.constantBuffer(
            value: 0.25, channelCount: 1, frameCount: frameCount
        ) else {
            XCTFail("Failed to create 32000-frame buffer")
            return
        }

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoder should handle 32000-frame buffer")
            return
        }

        // 32000 frames * 1 channel * 2 bytes = 64000 bytes
        XCTAssertEqual(encoded.count, 64000,
            "32000 mono frames should encode to 64000 bytes")

        // Spot-check first and last samples
        encoded.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)
            let expected = Int16(0.25 * 32767)

            XCTAssertEqual(Int16(littleEndian: int16Ptr[0]), expected,
                "First sample should be correct")
            XCTAssertEqual(Int16(littleEndian: int16Ptr[31999]), expected,
                "Last sample should be correct")
        }
    }

    /// Encoder should handle large stereo buffers (32000+ frames).
    func testEncoderHandlesLargeStereoBuffer() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 2)
        let frameCount: UInt32 = 48000  // 3 seconds @ 16kHz

        guard let buffer = MockAudioCapture.multichannelBuffer(
            values: [0.4, 0.6], frameCount: frameCount
        ) else {
            XCTFail("Failed to create 48000-frame stereo buffer")
            return
        }

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoder should handle 48000-frame stereo buffer")
            return
        }

        // 48000 frames * 2 channels * 2 bytes = 192000 bytes
        XCTAssertEqual(encoded.count, 192000,
            "48000 stereo frames should encode to 192000 bytes")

        // Spot-check interleaved output at boundaries
        let expectedCh0 = Int16(0.4 * 32767)
        let expectedCh1 = Int16(0.6 * 32767)

        encoded.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)

            // First frame
            XCTAssertEqual(Int16(littleEndian: int16Ptr[0]), expectedCh0, "First frame ch0")
            XCTAssertEqual(Int16(littleEndian: int16Ptr[1]), expectedCh1, "First frame ch1")

            // Last frame
            let lastIdx = (Int(frameCount) - 1) * 2
            XCTAssertEqual(Int16(littleEndian: int16Ptr[lastIdx]), expectedCh0, "Last frame ch0")
            XCTAssertEqual(Int16(littleEndian: int16Ptr[lastIdx + 1]), expectedCh1, "Last frame ch1")

            // Mid-point frame
            let midIdx = (Int(frameCount) / 2) * 2
            XCTAssertEqual(Int16(littleEndian: int16Ptr[midIdx]), expectedCh0, "Mid frame ch0")
            XCTAssertEqual(Int16(littleEndian: int16Ptr[midIdx + 1]), expectedCh1, "Mid frame ch1")
        }
    }

    /// Encoder should handle exactly one second at 48kHz (48000 frames) — a realistic hi-fi buffer.
    func testEncoderHandles48kHzLargeBuffer() {
        let encoder = AudioEncoder(sampleRate: 48000, channels: 1)
        let frameCount: UInt32 = 48000

        guard let buffer = MockAudioCapture.constantBuffer(
            value: -0.8, channelCount: 1, frameCount: frameCount, sampleRate: 48000
        ) else {
            XCTFail("Failed to create 48kHz 1-second buffer")
            return
        }

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoder should handle 48kHz buffer")
            return
        }

        XCTAssertEqual(encoded.count, 96000,
            "48000 mono frames should encode to 96000 bytes")

        encoded.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)
            let expected = Int16(-0.8 * 32767)  // -26213
            XCTAssertEqual(Int16(littleEndian: int16Ptr[0]), expected)
            XCTAssertEqual(Int16(littleEndian: int16Ptr[47999]), expected)
        }
    }
}
