import Foundation
import AVFoundation
@testable import WaiComputerKit

/// Mock implementation of AudioCaptureProtocol that generates synthetic PCM audio
/// buffers without requiring any hardware. Supports configurable frequency, sample rate,
/// channel count, and injection of pre-recorded audio data for deterministic testing.
final class MockAudioCapture: AudioCaptureProtocol, @unchecked Sendable {

    // MARK: - Configuration

    /// Sine wave frequency in Hz (default 440 = A4 note)
    let frequency: Double

    /// Audio capture config (sample rate, channel count, buffer size)
    let config: AudioCaptureConfig

    // MARK: - Protocol conformance

    private(set) var _isRecording = false
    var isRecording: Bool { _isRecording }
    private(set) var isPaused = false

    private var bufferContinuation: AsyncStream<AVAudioPCMBuffer>.Continuation?
    private(set) var audioBuffers: AsyncStream<AVAudioPCMBuffer>

    // MARK: - Internal state

    /// Running sample phase so sine wave is continuous across buffers
    private var phase: Double = 0.0

    /// Pre-recorded buffers to emit instead of generated sine waves.
    /// When non-empty, these are yielded in order and then cleared.
    private var injectedBuffers: [AVAudioPCMBuffer] = []

    /// Task that produces buffers on a timer while recording
    private var producerTask: Task<Void, Never>?

    /// How many buffers have been produced since startRecording()
    private(set) var producedBufferCount = 0

    /// Mirrors SystemAudioCapture.hasReceivedAudio — true once any buffer with
    /// non-zero samples has been generated or emitted.
    private(set) var hasReceivedAudio = false

    /// Interval between buffer emissions (seconds)
    let emitInterval: TimeInterval

    // MARK: - Init

    /// Create a mock audio capture.
    ///
    /// - Parameters:
    ///   - config: Audio format config (defaults to 16kHz mono, 2560-sample buffers)
    ///   - frequency: Sine wave frequency in Hz (default 440)
    ///   - emitInterval: Seconds between buffer emissions (default 0.16 = 160ms)
    init(
        config: AudioCaptureConfig = .default,
        frequency: Double = 440.0,
        emitInterval: TimeInterval = 0.16
    ) {
        self.config = config
        self.frequency = frequency
        self.emitInterval = emitInterval

        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        self.audioBuffers = stream
        self.bufferContinuation = continuation
    }

    // MARK: - Protocol methods

    func startRecording() async throws {
        if _isRecording {
            await stopRecording()
        }

        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        audioBuffers = stream
        bufferContinuation = continuation
        _isRecording = true
        isPaused = false
        phase = 0.0
        producedBufferCount = 0

        producerTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, self._isRecording else { break }
                if !self.isPaused {
                    self.emitNextBuffer()
                }
                try? await Task.sleep(for: .milliseconds(Int(self.emitInterval * 1000)))
            }
        }
    }

    func pauseRecording() async throws {
        guard _isRecording else { return }
        isPaused = true
    }

    func resumeRecording() async throws {
        guard _isRecording else { return }
        isPaused = false
    }

    func stopRecording() async {
        _isRecording = false
        isPaused = false
        producerTask?.cancel()
        producerTask = nil
        bufferContinuation?.finish()
    }

    // MARK: - Buffer injection

    /// Inject pre-recorded buffers for deterministic testing.
    /// These will be emitted in order before returning to sine wave generation.
    func injectBuffers(_ buffers: [AVAudioPCMBuffer]) {
        injectedBuffers.append(contentsOf: buffers)
    }

    /// Generate and immediately return a single sine wave buffer (synchronous, no recording needed).
    /// Useful for unit tests that need a buffer without starting the async producer.
    /// Sets `hasReceivedAudio = true` if the buffer contains non-zero samples.
    func generateBuffer() -> AVAudioPCMBuffer? {
        guard let buffer = makeSineBuffer() else { return nil }
        markReceivedIfNonZero(buffer)
        return buffer
    }

    /// Generate a buffer with a specific channel count, independent of the config.
    /// Useful for testing multichannel scenarios.
    func generateBuffer(channelCount: UInt32, frameCount: UInt32? = nil) -> AVAudioPCMBuffer? {
        let frames = frameCount ?? config.bufferSize
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: config.sampleRate,
            channels: AVAudioChannelCount(channelCount),
            interleaved: false
        ) else { return nil }

        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: AVAudioFrameCount(frames)
        ) else { return nil }

        buffer.frameLength = AVAudioFrameCount(frames)

        guard let floatData = buffer.floatChannelData else { return nil }

        for ch in 0..<Int(channelCount) {
            // Use different frequencies per channel so they are distinguishable
            let channelFreq = frequency * Double(ch + 1)
            let phaseIncrement = 2.0 * Double.pi * channelFreq / config.sampleRate
            var channelPhase = 0.0
            for i in 0..<Int(frames) {
                floatData[ch][i] = Float(sin(channelPhase))
                channelPhase += phaseIncrement
            }
        }

        return buffer
    }

    // MARK: - Private

    private func emitNextBuffer() {
        let buffer: AVAudioPCMBuffer

        if !injectedBuffers.isEmpty {
            buffer = injectedBuffers.removeFirst()
        } else {
            guard let generated = makeSineBuffer() else { return }
            buffer = generated
        }

        producedBufferCount += 1
        markReceivedIfNonZero(buffer)
        bufferContinuation?.yield(buffer)
    }

    /// Check whether `buffer` contains any non-zero sample and, if so,
    /// flip `hasReceivedAudio` to true (mirrors SystemAudioCapture behaviour).
    private func markReceivedIfNonZero(_ buffer: AVAudioPCMBuffer) {
        guard !hasReceivedAudio else { return }
        guard let floatData = buffer.floatChannelData else { return }
        let channels = Int(buffer.format.channelCount)
        let frames = Int(buffer.frameLength)
        for ch in 0..<channels {
            for i in 0..<frames {
                if floatData[ch][i] != 0 {
                    hasReceivedAudio = true
                    return
                }
            }
        }
    }

    private func makeSineBuffer() -> AVAudioPCMBuffer? {
        guard let format = config.format else { return nil }

        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: AVAudioFrameCount(config.bufferSize)
        ) else { return nil }

        buffer.frameLength = AVAudioFrameCount(config.bufferSize)

        guard let floatData = buffer.floatChannelData else { return nil }

        let phaseIncrement = 2.0 * Double.pi * frequency / config.sampleRate
        let channelCount = Int(config.channelCount)

        for i in 0..<Int(config.bufferSize) {
            let sample = Float(sin(phase))
            for ch in 0..<channelCount {
                floatData[ch][i] = sample
            }
            phase += phaseIncrement
        }

        return buffer
    }
}

// MARK: - Test helpers

extension MockAudioCapture {

    /// Create a mock configured for mono microphone-style capture (16kHz, 1ch)
    static func microphone(frequency: Double = 440.0) -> MockAudioCapture {
        MockAudioCapture(
            config: .default,
            frequency: frequency
        )
    }

    /// Create a mock configured for stereo system audio capture (16kHz, 2ch)
    static func systemAudio(frequency: Double = 440.0) -> MockAudioCapture {
        MockAudioCapture(
            config: AudioCaptureConfig(sampleRate: 16000, channelCount: 2, bufferSize: 2560),
            frequency: frequency
        )
    }

    /// Create a PCM buffer filled with a known constant value (useful for verifying encoding)
    static func constantBuffer(
        value: Float,
        channelCount: UInt32 = 1,
        frameCount: UInt32 = 2560,
        sampleRate: Double = 16000
    ) -> AVAudioPCMBuffer? {
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: AVAudioChannelCount(channelCount),
            interleaved: false
        ) else { return nil }

        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: AVAudioFrameCount(frameCount)
        ) else { return nil }

        buffer.frameLength = AVAudioFrameCount(frameCount)

        guard let floatData = buffer.floatChannelData else { return nil }

        for ch in 0..<Int(channelCount) {
            for i in 0..<Int(frameCount) {
                floatData[ch][i] = value
            }
        }

        return buffer
    }

    /// Create a PCM buffer where each channel has a distinct constant value.
    /// Channel 0 = values[0], Channel 1 = values[1], etc.
    static func multichannelBuffer(
        values: [Float],
        frameCount: UInt32 = 2560,
        sampleRate: Double = 16000
    ) -> AVAudioPCMBuffer? {
        let channelCount = UInt32(values.count)
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: AVAudioChannelCount(channelCount),
            interleaved: false
        ) else { return nil }

        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: AVAudioFrameCount(frameCount)
        ) else { return nil }

        buffer.frameLength = AVAudioFrameCount(frameCount)

        guard let floatData = buffer.floatChannelData else { return nil }

        for ch in 0..<Int(channelCount) {
            for i in 0..<Int(frameCount) {
                floatData[ch][i] = values[ch]
            }
        }

        return buffer
    }
}
