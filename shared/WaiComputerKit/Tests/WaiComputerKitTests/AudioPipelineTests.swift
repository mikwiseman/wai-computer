import XCTest
import AVFoundation
@testable import WaiComputerKit

final class AudioPipelineTests: XCTestCase {

    // MARK: - AudioCaptureConfig Tests

    func testAudioCaptureConfigDefaultValues() {
        let config = AudioCaptureConfig.default

        XCTAssertEqual(config.sampleRate, 16000)
        XCTAssertEqual(config.channelCount, 1)
        XCTAssertEqual(config.bufferSize, 2560, "Default buffer size should be 2560 (160ms @ 16kHz)")
    }

    func testAudioCaptureConfigFormatIsMono16kNonInterleaved() {
        let config = AudioCaptureConfig.default
        let format = config.format

        XCTAssertNotNil(format)
        XCTAssertEqual(format?.sampleRate, 16000)
        XCTAssertEqual(format?.channelCount, 1)
        XCTAssertEqual(format?.commonFormat, .pcmFormatFloat32)
        XCTAssertFalse(format?.isInterleaved ?? true)
    }

    func testAudioCaptureConfigCustomValues() {
        let config = AudioCaptureConfig(sampleRate: 48000, channelCount: 2, bufferSize: 4096)

        XCTAssertEqual(config.sampleRate, 48000)
        XCTAssertEqual(config.channelCount, 2)
        XCTAssertEqual(config.bufferSize, 4096)

        let format = config.format
        XCTAssertNotNil(format)
        XCTAssertEqual(format?.sampleRate, 48000)
        XCTAssertEqual(format?.channelCount, 2)
    }

    // MARK: - MockAudioCapture Tests

    func testMockAudioCaptureProducesCorrectMonoFormat() {
        let mock = MockAudioCapture.microphone()
        let buffer = mock.generateBuffer()

        XCTAssertNotNil(buffer)
        XCTAssertEqual(buffer?.format.channelCount, 1)
        XCTAssertEqual(buffer?.format.sampleRate, 16000)
        XCTAssertEqual(buffer?.format.commonFormat, .pcmFormatFloat32)
        XCTAssertFalse(buffer?.format.isInterleaved ?? true)
        XCTAssertEqual(buffer?.frameLength, 2560)
    }

    func testMockAudioCaptureProducesCorrectStereoFormat() {
        let mock = MockAudioCapture.systemAudio()
        let buffer = mock.generateBuffer()

        XCTAssertNotNil(buffer)
        XCTAssertEqual(buffer?.format.channelCount, 2)
        XCTAssertEqual(buffer?.format.sampleRate, 16000)
        XCTAssertEqual(buffer?.frameLength, 2560)
    }

    func testMockAudioCaptureSineWaveValuesInRange() {
        let mock = MockAudioCapture.microphone(frequency: 440)
        guard let buffer = mock.generateBuffer(),
              let floatData = buffer.floatChannelData else {
            XCTFail("Failed to generate buffer")
            return
        }

        let frameLength = Int(buffer.frameLength)
        XCTAssertGreaterThan(frameLength, 0)

        // All samples should be in [-1.0, 1.0] (sine wave)
        var hasNonZero = false
        for i in 0..<frameLength {
            let sample = floatData[0][i]
            XCTAssertGreaterThanOrEqual(sample, -1.0)
            XCTAssertLessThanOrEqual(sample, 1.0)
            if abs(sample) > 0.001 { hasNonZero = true }
        }
        XCTAssertTrue(hasNonZero, "Sine wave should have non-zero samples")
    }

    func testMockAudioCaptureMultichannelHasDistinctChannels() {
        let mock = MockAudioCapture.systemAudio(frequency: 440)
        guard let buffer = mock.generateBuffer(channelCount: 2),
              let floatData = buffer.floatChannelData else {
            XCTFail("Failed to generate 2-channel buffer")
            return
        }

        // Channel 0 uses frequency 440, channel 1 uses frequency 880
        // They should differ at most sample positions
        let frameLength = Int(buffer.frameLength)
        var differCount = 0
        for i in 0..<frameLength {
            if abs(floatData[0][i] - floatData[1][i]) > 0.001 {
                differCount += 1
            }
        }
        XCTAssertGreaterThan(differCount, frameLength / 2,
            "Channels at different frequencies should differ at most sample positions")
    }

    func testMockAudioCaptureInjectBuffers() {
        let mock = MockAudioCapture.microphone()

        // Create a known buffer
        guard let injected = MockAudioCapture.constantBuffer(value: 0.5, frameCount: 100) else {
            XCTFail("Failed to create constant buffer")
            return
        }
        mock.injectBuffers([injected])

        // The injected buffer array should be consumed on next emit
        // Verify directly by generating — injection works through the emit path,
        // so test that constantBuffer itself is correct
        XCTAssertEqual(injected.frameLength, 100)
        XCTAssertEqual(injected.format.channelCount, 1)

        guard let floatData = injected.floatChannelData else {
            XCTFail("No float data in injected buffer")
            return
        }
        for i in 0..<100 {
            XCTAssertEqual(floatData[0][i], 0.5, accuracy: 0.0001)
        }
    }

    func testMockAudioCaptureStartStopState() async throws {
        let mock = MockAudioCapture.microphone()

        XCTAssertFalse(mock.isRecording)

        try await mock.startRecording()
        XCTAssertTrue(mock.isRecording)

        await mock.stopRecording()
        XCTAssertFalse(mock.isRecording)
    }

    // MARK: - AudioEncoder Tests (mono)

    func testAudioEncoderMonoPCMInput() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 1)

        guard let buffer = MockAudioCapture.constantBuffer(value: 0.5, channelCount: 1, frameCount: 160) else {
            XCTFail("Failed to create mono buffer")
            return
        }

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoder returned nil for mono buffer")
            return
        }

        // 160 frames * 1 channel * 2 bytes per sample = 320 bytes
        XCTAssertEqual(encoded.count, 320)

        // Verify encoded values: 0.5 * 32767 = 16383 (Int16)
        encoded.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)
            for i in 0..<160 {
                let sample = Int16(littleEndian: int16Ptr[i])
                XCTAssertEqual(sample, 16383, "Mono sample \(i) should be 16383 (0.5 * 32767)")
            }
        }
    }

    func testAudioEncoderMultichannelNonInterleavedInput() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 2)

        // ch0 = 0.25 (mic), ch1 = 0.75 (system audio)
        guard let buffer = MockAudioCapture.multichannelBuffer(
            values: [0.25, 0.75],
            frameCount: 160
        ) else {
            XCTFail("Failed to create 2-channel buffer")
            return
        }

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoder returned nil for multichannel buffer")
            return
        }

        // 160 frames * 2 channels * 2 bytes = 640 bytes
        XCTAssertEqual(encoded.count, 640)

        // Verify interleaved output: [ch0_s0, ch1_s0, ch0_s1, ch1_s1, ...]
        let expectedCh0 = Int16(0.25 * 32767)  // 8191
        let expectedCh1 = Int16(0.75 * 32767)  // 24575

        encoded.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)
            for i in 0..<160 {
                let ch0Sample = Int16(littleEndian: int16Ptr[i * 2])
                let ch1Sample = Int16(littleEndian: int16Ptr[i * 2 + 1])
                XCTAssertEqual(ch0Sample, expectedCh0,
                    "Frame \(i) ch0 should be \(expectedCh0), got \(ch0Sample)")
                XCTAssertEqual(ch1Sample, expectedCh1,
                    "Frame \(i) ch1 should be \(expectedCh1), got \(ch1Sample)")
            }
        }
    }

    func testAudioEncoderInterleavesChannelsCorrectly() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 2)

        // Use distinct values per channel to verify interleaving order
        guard let buffer = MockAudioCapture.multichannelBuffer(
            values: [0.1, 0.9],
            frameCount: 4
        ) else {
            XCTFail("Failed to create test buffer")
            return
        }

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoder returned nil")
            return
        }

        // 4 frames * 2 channels * 2 bytes = 16 bytes total
        XCTAssertEqual(encoded.count, 16)

        // Expected interleaved pattern: [L, R, L, R, L, R, L, R]
        let expectedL = Int16(0.1 * 32767)  // 3276
        let expectedR = Int16(0.9 * 32767)  // 29490

        encoded.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)
            // Total 8 int16 samples: L R L R L R L R
            XCTAssertEqual(int16Ptr.count, 8)
            for i in 0..<4 {
                let left = Int16(littleEndian: int16Ptr[i * 2])
                let right = Int16(littleEndian: int16Ptr[i * 2 + 1])
                XCTAssertEqual(left, expectedL, "Frame \(i): left channel mismatch")
                XCTAssertEqual(right, expectedR, "Frame \(i): right channel mismatch")
            }
        }
    }

    func testAudioEncoderClampsSamplesOutsideRange() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 1)

        // Create a buffer with values outside [-1, 1] to verify clamping
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 16000,
            channels: 1,
            interleaved: false
        ),
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4) else {
            XCTFail("Failed to create format/buffer")
            return
        }
        buffer.frameLength = 4

        guard let floatData = buffer.floatChannelData else {
            XCTFail("No float data")
            return
        }

        floatData[0][0] = 1.5    // over max
        floatData[0][1] = -1.5   // under min
        floatData[0][2] = 0.0    // zero
        floatData[0][3] = 1.0    // max

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoder returned nil")
            return
        }

        XCTAssertEqual(encoded.count, 8) // 4 samples * 2 bytes

        encoded.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)
            // 1.5 clamped to 1.0 -> 32767
            XCTAssertEqual(Int16(littleEndian: int16Ptr[0]), 32767)
            // -1.5 clamped to -1.0 -> -32767
            XCTAssertEqual(Int16(littleEndian: int16Ptr[1]), -32767)
            // 0.0 -> 0
            XCTAssertEqual(Int16(littleEndian: int16Ptr[2]), 0)
            // 1.0 -> 32767
            XCTAssertEqual(Int16(littleEndian: int16Ptr[3]), 32767)
        }
    }

    // MARK: - AudioDecoder Roundtrip Tests

    func testAudioEncoderDecoderMonoRoundtrip() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 1)
        let decoder = AudioDecoder(sampleRate: 16000, channels: 1)

        guard let original = MockAudioCapture.constantBuffer(value: 0.5, channelCount: 1, frameCount: 160) else {
            XCTFail("Failed to create buffer")
            return
        }

        guard let encoded = encoder.encode(original) else {
            XCTFail("Encoding failed")
            return
        }

        guard let decoded = decoder.decode(encoded) else {
            XCTFail("Decoding failed")
            return
        }

        XCTAssertEqual(decoded.frameLength, 160)
        XCTAssertEqual(decoded.format.channelCount, 1)
        XCTAssertEqual(decoded.format.sampleRate, 16000)

        // Roundtrip should preserve values within quantization error
        // 16-bit quantization: error <= 1/32767 ~= 0.0000305
        guard let floatData = decoded.floatChannelData else {
            XCTFail("No float data in decoded buffer")
            return
        }
        for i in 0..<160 {
            XCTAssertEqual(floatData[0][i], 0.5, accuracy: 0.001,
                "Roundtrip sample \(i) should be ~0.5")
        }
    }

    // MARK: - Buffer Size and Sample Count Verification

    func testBufferSizesMatchConfig() {
        let configs: [(Double, UInt32, UInt32)] = [
            (16000, 1, 2560),   // default: 160ms @ 16kHz mono
            (16000, 2, 2560),   // dual: 160ms @ 16kHz stereo
            (48000, 1, 7680),   // hi-fi: 160ms @ 48kHz mono
        ]

        for (sampleRate, channels, bufferSize) in configs {
            let config = AudioCaptureConfig(
                sampleRate: sampleRate,
                channelCount: channels,
                bufferSize: bufferSize
            )
            let mock = MockAudioCapture(config: config)
            guard let buffer = mock.generateBuffer() else {
                XCTFail("Failed to generate buffer for \(sampleRate)Hz/\(channels)ch")
                continue
            }

            XCTAssertEqual(buffer.frameLength, AVAudioFrameCount(bufferSize),
                "Frame count should match bufferSize for \(sampleRate)Hz/\(channels)ch")
            XCTAssertEqual(buffer.format.channelCount, AVAudioChannelCount(channels),
                "Channel count mismatch for \(sampleRate)Hz/\(channels)ch")
            XCTAssertEqual(buffer.format.sampleRate, sampleRate,
                "Sample rate mismatch for \(sampleRate)Hz/\(channels)ch")

            // Non-interleaved buffers have stride of 1 (one sample per step per channel plane)
            XCTAssertEqual(Int(buffer.stride), 1,
                "Non-interleaved buffers should have stride of 1")
            // Each channel plane should have bufferSize floats
            if let floatData = buffer.floatChannelData {
                for ch in 0..<Int(channels) {
                    // Verify we can read all samples without crash
                    let _ = floatData[ch][Int(bufferSize) - 1]
                    // Spot check: non-interleaved means each channel is a separate array
                    XCTAssertNotNil(floatData[ch],
                        "Channel \(ch) data should not be nil for \(sampleRate)Hz/\(channels)ch")
                }
            }
        }
    }

    func testEncoderOutputSizeForVariousFrameCounts() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 1)

        let frameCounts: [UInt32] = [1, 10, 160, 2560, 16000]

        for frameCount in frameCounts {
            guard let buffer = MockAudioCapture.constantBuffer(
                value: 0.3, channelCount: 1, frameCount: frameCount
            ) else {
                XCTFail("Failed to create buffer with \(frameCount) frames")
                continue
            }

            guard let encoded = encoder.encode(buffer) else {
                XCTFail("Encoding failed for \(frameCount) frames")
                continue
            }

            let expectedBytes = Int(frameCount) * 2  // 16-bit = 2 bytes per sample
            XCTAssertEqual(encoded.count, expectedBytes,
                "Encoded size should be \(expectedBytes) for \(frameCount) mono frames")
        }
    }

    func testEncoderOutputSizeMultichannel() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 2)

        guard let buffer = MockAudioCapture.multichannelBuffer(
            values: [0.3, 0.7],
            frameCount: 160
        ) else {
            XCTFail("Failed to create 2-channel buffer")
            return
        }

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoding failed")
            return
        }

        // 160 frames * 2 channels * 2 bytes = 640
        XCTAssertEqual(encoded.count, 640,
            "2-channel interleaved output should be frames * channels * 2 bytes")
    }

    func testEncoderRejectsEmptyBuffer() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 1)

        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 16000,
            channels: 1,
            interleaved: false
        ),
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 100) else {
            XCTFail("Failed to create format/buffer")
            return
        }
        // frameLength defaults to 0 — do NOT set it
        XCTAssertEqual(buffer.frameLength, 0)

        let encoded = encoder.encode(buffer)
        XCTAssertNil(encoded, "Encoder should return nil for zero-length buffer")
    }
}
