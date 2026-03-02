import Foundation
import AVFoundation

/// Protocol for audio capture implementations
public protocol AudioCaptureProtocol: AnyObject, Sendable {
    /// Whether currently recording
    var isRecording: Bool { get }

    /// Start recording
    func startRecording() async throws

    /// Stop recording
    func stopRecording() async

    /// Stream of audio buffers
    var audioBuffers: AsyncStream<AVAudioPCMBuffer> { get }
}

/// Audio capture configuration
public struct AudioCaptureConfig: Sendable {
    public let sampleRate: Double
    public let channelCount: UInt32
    public let bufferSize: UInt32

    public static let `default` = AudioCaptureConfig(
        sampleRate: 16000,
        channelCount: 1,
        bufferSize: 2560  // 160ms @ 16kHz
    )

    public init(sampleRate: Double, channelCount: UInt32, bufferSize: UInt32) {
        self.sampleRate = sampleRate
        self.channelCount = channelCount
        self.bufferSize = bufferSize
    }

    public var format: AVAudioFormat? {
        return AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: AVAudioChannelCount(channelCount),
            interleaved: false
        )
    }
}

/// Microphone audio capture using AVAudioEngine
public final class MicrophoneCapture: @unchecked Sendable {
    private let engine = AVAudioEngine()
    private let config: AudioCaptureConfig

    private var bufferContinuation: AsyncStream<AVAudioPCMBuffer>.Continuation?
    public private(set) var audioBuffers: AsyncStream<AVAudioPCMBuffer>!

    private var _isRecording = false
    public var isRecording: Bool { _isRecording }

    public init(config: AudioCaptureConfig = .default) {
        self.config = config
        setupBufferStream()
    }

    private func setupBufferStream() {
        audioBuffers = AsyncStream { continuation in
            self.bufferContinuation = continuation
        }
    }

    /// Start recording from microphone
    public func startRecording() async throws {
        #if os(iOS)
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.record, mode: .default)
        try audioSession.setActive(true)
        #endif

        let inputNode = engine.inputNode
        let inputFormat = inputNode.outputFormat(forBus: 0)

        // Create converter to target format
        guard let targetFormat = config.format else {
            throw AudioCaptureError.invalidFormat
        }

        let converter = AVAudioConverter(from: inputFormat, to: targetFormat)

        inputNode.installTap(onBus: 0, bufferSize: AVAudioFrameCount(config.bufferSize), format: inputFormat) { [weak self] buffer, _ in
            guard let self = self, let converter = converter else { return }

            // Convert to target format
            guard let convertedBuffer = AVAudioPCMBuffer(
                pcmFormat: targetFormat,
                frameCapacity: AVAudioFrameCount(self.config.bufferSize)
            ) else { return }

            var error: NSError?
            let status = converter.convert(to: convertedBuffer, error: &error) { inNumPackets, outStatus in
                outStatus.pointee = .haveData
                return buffer
            }

            if status == .haveData {
                self.bufferContinuation?.yield(convertedBuffer)
            }
        }

        try engine.start()
        _isRecording = true
    }

    /// Stop recording
    public func stopRecording() async {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        _isRecording = false
        bufferContinuation?.finish()
        setupBufferStream()
    }
}

public enum AudioCaptureError: Error, Sendable {
    case invalidFormat
    case permissionDenied
    case engineStartFailed
}
