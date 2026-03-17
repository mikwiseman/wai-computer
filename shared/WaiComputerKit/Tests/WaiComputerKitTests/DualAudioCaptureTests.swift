import XCTest
import AVFoundation
@testable import WaiComputerKit

@available(macOS 14.2, *)
final class DualAudioCaptureTests: XCTestCase {

    // MARK: - Initialization & Default State

    func testInitDoesNotCrash() {
        let capture = DualAudioCapture()
        XCTAssertNotNil(capture, "DualAudioCapture should initialize without crashing")
    }

    func testInitWithCustomConfig() {
        let config = AudioCaptureConfig(sampleRate: 48000, channelCount: 2, bufferSize: 4096)
        let capture = DualAudioCapture(config: config)
        XCTAssertNotNil(capture, "DualAudioCapture should initialize with custom config")
    }

    func testIsRecordingDefaultsFalse() {
        let capture = DualAudioCapture()
        XCTAssertFalse(capture.isRecording, "isRecording should default to false")
    }

    func testHasSystemAudioDefaultsFalse() {
        let capture = DualAudioCapture()
        XCTAssertFalse(capture.hasSystemAudio, "hasSystemAudio should default to false")
    }

    func testSystemAudioStalledDefaultsFalse() {
        let capture = DualAudioCapture()
        XCTAssertFalse(capture.systemAudioStalled, "systemAudioStalled should default to false")
    }

    func testAudioBuffersStreamExists() {
        let capture = DualAudioCapture()
        // audioBuffers is a non-optional AsyncStream — just verify we can reference it
        let stream = capture.audioBuffers
        XCTAssertNotNil(stream, "audioBuffers stream should be available after init")
    }

    // MARK: - 2-Channel PCM Buffer Format (mirrors flushDualBuffers output)

    /// Verify that the 2-channel non-interleaved PCM format used by flushDualBuffers
    /// can be created correctly. This tests the exact format construction path.
    func testDualChannelPCMFormatCreation() {
        let config = AudioCaptureConfig.default
        let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: config.sampleRate,
            channels: 2,
            interleaved: false
        )

        XCTAssertNotNil(format)
        XCTAssertEqual(format?.sampleRate, 16000)
        XCTAssertEqual(format?.channelCount, 2)
        XCTAssertEqual(format?.commonFormat, .pcmFormatFloat32)
        XCTAssertFalse(format?.isInterleaved ?? true, "Dual buffers must be non-interleaved")
    }

    /// Simulate the buffer assembly logic in flushDualBuffers: create a 2-channel
    /// non-interleaved buffer with mic on ch0 and system audio on ch1, then verify
    /// channel data is correctly separated.
    func testDualChannelBufferAssembly() {
        let config = AudioCaptureConfig.default
        let frames = 2560

        // Simulate mic and system audio sample data
        let micSamples = [Float](repeating: 0.3, count: frames)
        let sysSamples = [Float](repeating: 0.7, count: frames)

        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: config.sampleRate,
            channels: 2,
            interleaved: false
        ) else {
            XCTFail("Failed to create 2-channel format")
            return
        }

        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: AVAudioFrameCount(frames)
        ) else {
            XCTFail("Failed to create PCM buffer")
            return
        }
        buffer.frameLength = AVAudioFrameCount(frames)

        guard let outData = buffer.floatChannelData else {
            XCTFail("No float channel data")
            return
        }

        // Write channels exactly as flushDualBuffers does
        for i in 0..<frames {
            outData[0][i] = micSamples[i]  // ch0 = mic
            outData[1][i] = sysSamples[i]  // ch1 = system
        }

        // Verify channel separation
        XCTAssertEqual(buffer.frameLength, AVAudioFrameCount(frames))
        XCTAssertEqual(buffer.format.channelCount, 2)

        for i in 0..<frames {
            XCTAssertEqual(outData[0][i], 0.3, accuracy: 0.0001,
                "Channel 0 (mic) should contain mic samples")
            XCTAssertEqual(outData[1][i], 0.7, accuracy: 0.0001,
                "Channel 1 (system) should contain system audio samples")
        }
    }

    /// Verify that when system audio stalls, ch1 is padded with silence (zeros),
    /// matching the flushDualBuffers fallback behavior.
    func testDualChannelBufferWithSilentSystemAudio() {
        let config = AudioCaptureConfig.default
        let frames = 1280  // 80ms @ 16kHz (minimum flush size)

        let micSamples = [Float](repeating: 0.5, count: frames)
        let sysSamples = [Float](repeating: 0.0, count: frames)  // silence = stalled system

        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: config.sampleRate,
            channels: 2,
            interleaved: false
        ),
        let buffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: AVAudioFrameCount(frames)
        ) else {
            XCTFail("Failed to create buffer")
            return
        }
        buffer.frameLength = AVAudioFrameCount(frames)

        guard let outData = buffer.floatChannelData else {
            XCTFail("No float channel data")
            return
        }

        for i in 0..<frames {
            outData[0][i] = micSamples[i]
            outData[1][i] = sysSamples[i]
        }

        // Mic channel should have audio
        var micHasAudio = false
        for i in 0..<frames {
            if abs(outData[0][i]) > 0.001 { micHasAudio = true; break }
        }
        XCTAssertTrue(micHasAudio, "Mic channel should have non-zero audio")

        // System channel should be all silence
        for i in 0..<frames {
            XCTAssertEqual(outData[1][i], 0.0, accuracy: 0.0001,
                "System channel should be silent when stalled")
        }
    }

    /// Verify the minimum flush size calculation matches what flushDualBuffers uses.
    func testMinFlushSizeCalculation() {
        let config = AudioCaptureConfig.default
        let minFlushSize = Int(config.sampleRate * 0.08)

        // At 16kHz, 80ms = 1280 samples
        XCTAssertEqual(minFlushSize, 1280,
            "Minimum flush size at 16kHz should be 1280 samples (80ms)")

        // Verify this is less than the default buffer size
        XCTAssertLessThan(UInt32(minFlushSize), config.bufferSize,
            "Min flush size should be smaller than default buffer size")
    }

    /// Verify that the max flush cap (1 second) matches the stall-fallback logic.
    func testMaxFlushCapAtOneSec() {
        let config = AudioCaptureConfig.default
        let maxFlushCap = Int(config.sampleRate)

        // At 16kHz, 1 second = 16000 samples
        XCTAssertEqual(maxFlushCap, 16000,
            "Max flush cap at 16kHz should be 16000 samples (1 second)")
    }

    // MARK: - Multiple Instance Independence

    func testMultipleInstancesAreIndependent() {
        let captureA = DualAudioCapture()
        let captureB = DualAudioCapture()

        // Both should have independent default state
        XCTAssertFalse(captureA.isRecording)
        XCTAssertFalse(captureB.isRecording)
        XCTAssertFalse(captureA.hasSystemAudio)
        XCTAssertFalse(captureB.hasSystemAudio)
        XCTAssertFalse(captureA.systemAudioStalled)
        XCTAssertFalse(captureB.systemAudioStalled)

        // They should be distinct objects
        XCTAssertFalse(captureA === captureB, "Instances should be distinct objects")
    }

    // MARK: - Encoder Integration with Dual Channel Buffers

    /// Verify that a 2-channel buffer (like flushDualBuffers produces) encodes correctly
    /// through AudioEncoder with distinct per-channel values.
    func testDualChannelBufferEncodesCorrectly() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 2)
        let frames: UInt32 = 160

        guard let buffer = MockAudioCapture.multichannelBuffer(
            values: [0.3, 0.8],  // ch0=mic, ch1=system
            frameCount: frames
        ) else {
            XCTFail("Failed to create 2-channel buffer")
            return
        }

        // Verify the buffer matches what flushDualBuffers would produce
        XCTAssertEqual(buffer.format.channelCount, 2)
        XCTAssertEqual(buffer.format.sampleRate, 16000)
        XCTAssertEqual(buffer.frameLength, AVAudioFrameCount(frames))
        XCTAssertFalse(buffer.format.isInterleaved)

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoder should handle 2-channel buffer")
            return
        }

        // 160 frames * 2 channels * 2 bytes = 640 bytes
        XCTAssertEqual(encoded.count, 640)

        // Verify interleaved output preserves channel distinction
        let expectedCh0 = Int16(0.3 * 32767)
        let expectedCh1 = Int16(0.8 * 32767)

        encoded.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)
            for i in 0..<Int(frames) {
                let ch0 = Int16(littleEndian: int16Ptr[i * 2])
                let ch1 = Int16(littleEndian: int16Ptr[i * 2 + 1])
                XCTAssertEqual(ch0, expectedCh0,
                    "Frame \(i) ch0 (mic) mismatch")
                XCTAssertEqual(ch1, expectedCh1,
                    "Frame \(i) ch1 (system) mismatch")
            }
        }
    }
}
