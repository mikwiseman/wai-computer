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
    private var audioProcessor: CaptureAudioProcessor?

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
        os_unfair_lock_lock(continuationLock)
        bufferContinuation = continuation
        os_unfair_lock_unlock(continuationLock)
    }

    private func finishBufferStream() {
        os_unfair_lock_lock(continuationLock)
        bufferContinuation?.finish()
        os_unfair_lock_unlock(continuationLock)
    }

    private func setAudioProcessor(_ processor: CaptureAudioProcessor?) {
        os_unfair_lock_lock(continuationLock)
        audioProcessor = processor
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
        micLog.info("[Mic] Native input format: \(nativeSR)Hz, \(nativeCh)ch")

        guard let processor = CaptureAudioProcessor(config: config) else {
            throw AudioCaptureError.invalidFormat
        }
        processor.reset()
        setAudioProcessor(processor)
        let targetSR = config.sampleRate
        let targetCh = config.channelCount
        micLog.info("[Mic] Target format: \(targetSR)Hz, \(targetCh)ch")

        // On macOS, installTap on inputNode does NOT support format conversion —
        // passing a non-nil format different from native throws an NSException.
        // Install with nil (= native format) and convert manually.
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(
            onBus: 0,
            bufferSize: AVAudioFrameCount(config.bufferSize),
            format: nil
        ) { [weak self] buffer, _ in
            guard let self = self else { return }
            os_unfair_lock_lock(self.continuationLock)
            let processor = self.audioProcessor
            let continuation = self.bufferContinuation
            os_unfair_lock_unlock(self.continuationLock)
            guard let outBuffer = processor?.process(buffer) else { return }
            continuation?.yield(outBuffer)
        }

        micLog.info("[Mic] Starting engine...")
        engine.prepare()
        do {
            try engine.start()
        } catch {
            inputNode.removeTap(onBus: 0)
            engine.stop()
            throw error
        }
        _isRecording = true
        micLog.info("[Mic] Engine started, recording = true")
    }

    /// Stop recording
    public func stopRecording() async {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        _isRecording = false
        logProcessingSummary(context: "stop")
        finishBufferStream()
        setAudioProcessor(nil)
        setupBufferStream()
    }

    private func logProcessingSummary(context: String) {
        guard let stats = audioProcessor?.snapshot else { return }
        if stats.hasFailures {
            micLog.error(
                "[Mic] Capture summary (\(context)): received=\(stats.buffersReceived), yielded=\(stats.buffersYielded), empty=\(stats.emptyBuffers), missingFloat=\(stats.missingFloatData), allocFailures=\(stats.allocationFailures), resamplerBuildFailures=\(stats.resamplerBuildFailures), conversionFailures=\(stats.conversionFailures), resamplerRebuilds=\(stats.resamplerRebuilds), passthroughCopies=\(stats.passthroughCopies)"
            )
        } else {
            micLog.info(
                "[Mic] Capture summary (\(context)): received=\(stats.buffersReceived), yielded=\(stats.buffersYielded), resamplerRebuilds=\(stats.resamplerRebuilds), passthroughCopies=\(stats.passthroughCopies)"
            )
        }
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
