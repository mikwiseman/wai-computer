import Foundation
import AVFoundation
import os

private let micLog = Logger(subsystem: "is.waiwai.computer.kit", category: "mic")

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
public final class MicrophoneCapture: AudioCaptureProtocol, @unchecked Sendable {
    private let engine = AVAudioEngine()
    private let config: AudioCaptureConfig

    private var bufferContinuation: AsyncStream<AVAudioPCMBuffer>.Continuation?
    private let continuationLock: UnsafeMutablePointer<os_unfair_lock>
    public private(set) var audioBuffers: AsyncStream<AVAudioPCMBuffer>

    private var _isRecording = false
    public var isRecording: Bool { _isRecording }

    public init(config: AudioCaptureConfig = .default) {
        self.config = config
        self.continuationLock = .allocate(capacity: 1)
        self.continuationLock.initialize(to: os_unfair_lock())
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        self.audioBuffers = stream
        self.bufferContinuation = continuation
    }

    private func setupBufferStream() {
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        audioBuffers = stream
        bufferContinuation = continuation
    }

    private func finishBufferStream() {
        os_unfair_lock_lock(continuationLock)
        bufferContinuation?.finish()
        os_unfair_lock_unlock(continuationLock)
    }

    /// Start recording from microphone
    public func startRecording() async throws {
        // Guard against double-start
        if _isRecording {
            micLog.warning("[Mic] startRecording called while already recording — stopping first")
            await stopRecording()
        }

        #if os(iOS)
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.record, mode: .default)
        try audioSession.setActive(true)
        #endif

        let inputNode = engine.inputNode
        let nativeFormat = inputNode.outputFormat(forBus: 0)
        let nativeSR = nativeFormat.sampleRate
        let nativeCh = nativeFormat.channelCount
        micLog.warning("[Mic] Native input format: \(nativeSR)Hz, \(nativeCh)ch")

        guard let targetFormat = config.format else {
            throw AudioCaptureError.invalidFormat
        }
        let targetSR = config.sampleRate
        let targetCh = config.channelCount
        micLog.warning("[Mic] Target format: \(targetSR)Hz, \(targetCh)ch")

        // On macOS, installTap on inputNode does NOT support format conversion —
        // passing a non-nil format different from native throws an NSException.
        // Install with nil (= native format) and convert manually.
        var tapCount = 0
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(
            onBus: 0,
            bufferSize: AVAudioFrameCount(config.bufferSize),
            format: nil
        ) { [weak self] buffer, _ in
            guard let self = self else { return }
            tapCount += 1

            // Manual conversion: native format → 16kHz mono float32
            guard let floatData = buffer.floatChannelData else {
                if tapCount <= 5 { micLog.error("[Mic] Tap #\(tapCount): no float data") }
                return
            }
            let srcFrames = Int(buffer.frameLength)
            if srcFrames == 0 { return }

            // Take channel 0 (mono from potentially stereo)
            let srcSamples = floatData[0]

            // Downsample: simple decimation with averaging
            let ratio = nativeSR / targetSR
            let outFrames = Int(Double(srcFrames) / ratio)
            if outFrames == 0 { return }

            guard let outBuffer = AVAudioPCMBuffer(
                pcmFormat: targetFormat,
                frameCapacity: AVAudioFrameCount(outFrames)
            ) else {
                if tapCount <= 5 { micLog.error("[Mic] Failed to create output buffer") }
                return
            }
            outBuffer.frameLength = AVAudioFrameCount(outFrames)

            guard let outData = outBuffer.floatChannelData else { return }
            let dst = outData[0]

            if ratio <= 1.01 {
                // No resampling needed — just copy
                for i in 0..<outFrames {
                    dst[i] = srcSamples[i]
                }
            } else {
                // Downsample with simple averaging (good enough for speech)
                let intRatio = Int(ratio.rounded())
                for i in 0..<outFrames {
                    let srcStart = Int(Double(i) * ratio)
                    var sum: Float = 0
                    let count = min(intRatio, srcFrames - srcStart)
                    for j in 0..<count {
                        sum += srcSamples[srcStart + j]
                    }
                    dst[i] = sum / Float(count)
                }
            }

            if tapCount <= 3 || tapCount % 100 == 0 {
                micLog.warning("[Mic] Tap #\(tapCount): \(srcFrames)@\(nativeSR)Hz → \(outFrames)@\(targetSR)Hz")
            }

            os_unfair_lock_lock(self.continuationLock)
            self.bufferContinuation?.yield(outBuffer)
            os_unfair_lock_unlock(self.continuationLock)
        }

        micLog.warning("[Mic] Starting engine...")
        engine.prepare()
        do {
            try engine.start()
        } catch {
            inputNode.removeTap(onBus: 0)
            engine.stop()
            throw error
        }
        _isRecording = true
        micLog.warning("[Mic] Engine started, recording = true")
    }

    /// Stop recording
    public func stopRecording() async {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        _isRecording = false
        finishBufferStream()
        setupBufferStream()
    }

    deinit {
        continuationLock.deinitialize(count: 1)
        continuationLock.deallocate()
    }
}

public enum AudioCaptureError: Error, Sendable {
    case invalidFormat
    case permissionDenied
    case engineStartFailed
    case leaseInUse
    case notStarted
}
