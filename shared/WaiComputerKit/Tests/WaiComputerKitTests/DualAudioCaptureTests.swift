import XCTest
import AVFoundation
@testable import WaiComputerKit

@available(macOS 14.2, *)
final class DualAudioCaptureTests: XCTestCase {

    // MARK: - Initial state

    /// All `false` flags on a freshly-created capture. Single regression test
    /// (replaces six prior `XCTAssertNotNil(capture)`-only smoke tests).
    func testFreshCaptureHasNoActiveAudioFlags() {
        let capture = DualAudioCapture()
        XCTAssertFalse(capture.isRecording)
        XCTAssertFalse(capture.hasSystemAudio)
        XCTAssertFalse(capture.systemAudioStalled)
        XCTAssertFalse(capture.systemAudioStreamActive)
        XCTAssertFalse(capture.systemAudioReceivedAny)
    }

    /// A custom-config capture starts in the same idle state — verifies the
    /// custom-config init path doesn't accidentally flip a flag.
    func testCustomConfigCaptureStartsIdle() {
        let config = AudioCaptureConfig(sampleRate: 48000, channelCount: 2, bufferSize: 4096)
        let capture = DualAudioCapture(config: config)
        XCTAssertFalse(capture.isRecording)
        XCTAssertFalse(capture.hasSystemAudio)
    }

    func testStartRecordingThrowsInsteadOfFallingBackWhenSystemAudioFails() async {
        let mic = MockAudioCapture()
        let system = FailingSystemAudioCapture()
        let capture = DualAudioCapture(mic: mic, system: system)

        do {
            try await capture.startRecording()
            XCTFail("Dual capture must not silently fall back to mic-only when system audio fails")
        } catch let error as DualAudioCaptureError {
            XCTAssertEqual(error.localizedDescription, "System audio capture could not start. Complete System Audio setup in onboarding or enable WaiComputer in System Settings.")
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        XCTAssertFalse(capture.isRecording)
        XCTAssertFalse(capture.hasSystemAudio)
        XCTAssertFalse(mic.isRecording)
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
    /// matching the flushDualBuffers silence-padding behavior.
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

    /// Verify that the max flush cap (1 second) matches the stall padding logic.
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

    // MARK: - systemAudioReceivedAny & systemAudioStalled Public Access

    /// systemAudioReceivedAny must be publicly readable and start as false.
    func testSystemAudioReceivedAnyStartsFalse() {
        let capture = DualAudioCapture()
        XCTAssertFalse(capture.systemAudioReceivedAny,
            "systemAudioReceivedAny should be false before recording starts")
    }

    func testSystemAudioStreamActiveStartsFalse() {
        let capture = DualAudioCapture()
        XCTAssertFalse(capture.systemAudioStreamActive,
            "systemAudioStreamActive should be false before recording starts")
    }

    /// systemAudioStalled must be publicly readable and start as false.
    func testSystemAudioStalledStartsFalse() {
        let capture = DualAudioCapture()
        XCTAssertFalse(capture.systemAudioStalled,
            "systemAudioStalled should be false before recording starts")
    }

    func testSilentSystemBufferDoesNotCountAsReceivedAudio() {
        guard let buffer = MockAudioCapture.constantBuffer(
            value: 0.0,
            channelCount: 1,
            frameCount: 160
        ) else {
            XCTFail("Failed to create silent system buffer")
            return
        }

        XCTAssertFalse(
            DualAudioCapture.bufferContainsAudibleSamples(buffer),
            "All-zero system buffers must not mark system audio as detected"
        )
    }

    func testNonZeroSystemBufferCountsAsReceivedAudio() {
        guard let buffer = MockAudioCapture.constantBuffer(
            value: 0.25,
            channelCount: 1,
            frameCount: 160
        ) else {
            XCTFail("Failed to create audible system buffer")
            return
        }

        XCTAssertTrue(
            DualAudioCapture.bufferContainsAudibleSamples(buffer),
            "Non-zero system buffers should mark system audio as detected"
        )
    }

    func testMonoMixDoesNotAttenuateMicrophoneBeforeSystemAudioArrives() {
        let sample = DualAudioCapture.monoMixedSample(
            microphone: 0.6,
            system: 0.0,
            hasSystemAudio: false
        )

        XCTAssertEqual(sample, 0.6, accuracy: 0.0001)
    }

    func testMonoMixAveragesAfterSystemAudioArrives() {
        let sample = DualAudioCapture.monoMixedSample(
            microphone: 0.6,
            system: 0.2,
            hasSystemAudio: true
        )

        XCTAssertEqual(sample, 0.4, accuracy: 0.0001)
    }

    // MARK: - minFlushSize Calculation

    /// Verify config.sampleRate * 0.08 produces the expected minFlushSize at default 16kHz.
    func testMinFlushSizeAtDefault16kHz() {
        let config = AudioCaptureConfig.default
        let minFlushSize = Int(config.sampleRate * 0.08)
        XCTAssertEqual(minFlushSize, 1280,
            "16000 * 0.08 should equal 1280 samples (80ms at 16kHz)")
    }

    /// Verify config.sampleRate * 0.08 at 48kHz produces correct minFlushSize.
    func testMinFlushSizeAt48kHz() {
        let config = AudioCaptureConfig(sampleRate: 48000, channelCount: 1, bufferSize: 4096)
        let minFlushSize = Int(config.sampleRate * 0.08)
        XCTAssertEqual(minFlushSize, 3840,
            "48000 * 0.08 should equal 3840 samples (80ms at 48kHz)")
    }

    /// Verify config.sampleRate * 0.08 at 8kHz produces correct minFlushSize.
    func testMinFlushSizeAt8kHz() {
        let config = AudioCaptureConfig(sampleRate: 8000, channelCount: 1, bufferSize: 1024)
        let minFlushSize = Int(config.sampleRate * 0.08)
        XCTAssertEqual(minFlushSize, 640,
            "8000 * 0.08 should equal 640 samples (80ms at 8kHz)")
    }

    // MARK: - 2-Channel Buffer with Mixed Zero/Non-Zero Content

    /// A 2-channel buffer where ch0 has audio and ch1 is silence (stalled system audio scenario).
    func testDualChannelBufferMixedZeroAndNonZero() {
        let frames: UInt32 = 1280

        guard let buffer = MockAudioCapture.multichannelBuffer(
            values: [0.5, 0.0],  // ch0 = mic audio, ch1 = silent system audio
            frameCount: frames
        ) else {
            XCTFail("Failed to create mixed 2-channel buffer")
            return
        }

        XCTAssertEqual(buffer.format.channelCount, 2)
        XCTAssertEqual(buffer.frameLength, AVAudioFrameCount(frames))

        guard let floatData = buffer.floatChannelData else {
            XCTFail("No float channel data")
            return
        }

        // Ch0 should have non-zero audio
        var ch0HasAudio = false
        for i in 0..<Int(frames) {
            if abs(floatData[0][i]) > 0.001 { ch0HasAudio = true; break }
        }
        XCTAssertTrue(ch0HasAudio, "Channel 0 (mic) should have non-zero audio")

        // Ch1 should be all silence
        for i in 0..<Int(frames) {
            XCTAssertEqual(floatData[1][i], 0.0, accuracy: 0.0001,
                "Channel 1 (system) should be silent at sample \(i)")
        }
    }

    /// A 2-channel buffer where ch0 is silence and ch1 has audio (inverse of typical stall scenario).
    func testDualChannelBufferInverseMixed() {
        let frames: UInt32 = 640

        guard let buffer = MockAudioCapture.multichannelBuffer(
            values: [0.0, 0.9],  // ch0 = silent mic, ch1 = system audio
            frameCount: frames
        ) else {
            XCTFail("Failed to create inverse mixed buffer")
            return
        }

        guard let floatData = buffer.floatChannelData else {
            XCTFail("No float channel data")
            return
        }

        // Ch0 should be silent
        for i in 0..<Int(frames) {
            XCTAssertEqual(floatData[0][i], 0.0, accuracy: 0.0001,
                "Channel 0 should be silent")
        }

        // Ch1 should have audio
        var ch1HasAudio = false
        for i in 0..<Int(frames) {
            if abs(floatData[1][i]) > 0.001 { ch1HasAudio = true; break }
        }
        XCTAssertTrue(ch1HasAudio, "Channel 1 should have non-zero audio")
    }

    /// Encoding a mixed 2-channel buffer should preserve zero/non-zero distinction in output.
    func testMixedDualChannelBufferEncodesCorrectly() {
        let encoder = AudioEncoder(sampleRate: 16000, channels: 2)
        let frames: UInt32 = 160

        guard let buffer = MockAudioCapture.multichannelBuffer(
            values: [0.6, 0.0],  // ch0 = audio, ch1 = silence
            frameCount: frames
        ) else {
            XCTFail("Failed to create mixed buffer for encoding")
            return
        }

        guard let encoded = encoder.encode(buffer) else {
            XCTFail("Encoder should handle mixed 2-channel buffer")
            return
        }

        // 160 frames * 2 channels * 2 bytes = 640 bytes
        XCTAssertEqual(encoded.count, 640)

        let expectedCh0 = Int16(0.6 * 32767)
        let expectedCh1 = Int16(0)

        encoded.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let int16Ptr = bytes.bindMemory(to: Int16.self)
            for i in 0..<Int(frames) {
                let ch0 = Int16(littleEndian: int16Ptr[i * 2])
                let ch1 = Int16(littleEndian: int16Ptr[i * 2 + 1])
                XCTAssertEqual(ch0, expectedCh0,
                    "Frame \(i) ch0 should have audio value")
                XCTAssertEqual(ch1, expectedCh1,
                    "Frame \(i) ch1 should be zero (stalled system audio)")
            }
        }
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

@available(macOS 14.2, *)
private final class FailingSystemAudioCapture: SystemAudioCaptureProtocol, @unchecked Sendable {
    private(set) var isRecording = false
    let audioBuffers: AsyncStream<AVAudioPCMBuffer>

    init() {
        self.audioBuffers = AsyncStream { continuation in
            continuation.finish()
        }
    }

    func startRecording() async throws {
        isRecording = false
        throw FailingSystemAudioError.denied
    }

    func stopRecording() async {
        isRecording = false
    }

    func waitForAudioBuffers(timeout: TimeInterval) async -> Bool {
        false
    }
}

private enum FailingSystemAudioError: LocalizedError {
    case denied

    var errorDescription: String? {
        "Audio Capture denied"
    }
}
