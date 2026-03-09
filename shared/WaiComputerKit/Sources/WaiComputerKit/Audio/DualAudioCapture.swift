import Foundation
import AVFoundation
import os

private let dualLog = Logger(subsystem: "com.waicomputer.kit", category: "dual-audio")

/// Captures both microphone and system audio simultaneously.
///
/// When both sources are active, produces 2-channel non-interleaved PCM buffers
/// (ch0 = mic, ch1 = system audio). When system audio is unavailable,
/// produces mono buffers from mic only.
@available(macOS 14.2, *)
public final class DualAudioCapture: AudioCaptureProtocol, @unchecked Sendable {
    private let mic: MicrophoneCapture
    private let system: SystemAudioCapture
    private let config: AudioCaptureConfig

    private var bufferContinuation: AsyncStream<AVAudioPCMBuffer>.Continuation?
    public private(set) var audioBuffers: AsyncStream<AVAudioPCMBuffer>

    private var _isRecording = false
    public var isRecording: Bool { _isRecording }

    /// Whether system audio is active (false = mic-only)
    public private(set) var hasSystemAudio = false

    private var micTask: Task<Void, Never>?
    private var systemTask: Task<Void, Never>?
    private var flushTask: Task<Void, Never>?

    private let lock = NSLock()
    private var micBuffer: [Float] = []
    private var systemBuffer: [Float] = []

    public init(config: AudioCaptureConfig = .default) {
        self.config = config
        self.mic = MicrophoneCapture(config: config)
        self.system = SystemAudioCapture(config: config)
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        self.audioBuffers = stream
        self.bufferContinuation = continuation
    }

    private func setupBufferStream() {
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        audioBuffers = stream
        bufferContinuation = continuation
    }

    public func startRecording() async throws {
        if _isRecording {
            dualLog.warning("[Dual] Already recording — stopping first")
            await stopRecording()
        }

        // Start mic (required)
        try await mic.startRecording()
        dualLog.warning("[Dual] Microphone started")

        // Try system audio
        do {
            try await system.startRecording()
            hasSystemAudio = true
            dualLog.warning("[Dual] System audio started — 2-channel mode")
        } catch {
            hasSystemAudio = false
            dualLog.warning("[Dual] System audio unavailable: \(error.localizedDescription) — mic-only")
        }

        _isRecording = true

        if hasSystemAudio {
            startDualMode()
        } else {
            startMicOnlyMode()
        }
    }

    /// Dual mode: accumulate both streams, flush as 2-channel buffers.
    private func startDualMode() {
        micTask = Task { [weak self] in
            guard let self else { return }
            for await buffer in self.mic.audioBuffers {
                guard let floatData = buffer.floatChannelData else { continue }
                let frames = Int(buffer.frameLength)
                let samples = Array(UnsafeBufferPointer(start: floatData[0], count: frames))
                self.lock.lock()
                self.micBuffer.append(contentsOf: samples)
                self.lock.unlock()
            }
        }

        systemTask = Task { [weak self] in
            guard let self else { return }
            for await buffer in self.system.audioBuffers {
                guard let floatData = buffer.floatChannelData else { continue }
                let frames = Int(buffer.frameLength)
                let samples = Array(UnsafeBufferPointer(start: floatData[0], count: frames))
                self.lock.lock()
                self.systemBuffer.append(contentsOf: samples)
                self.lock.unlock()
            }
        }

        flushTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(0.16))
                guard !Task.isCancelled else { break }
                self?.flushDualBuffers()
            }
        }
    }

    /// Mic-only mode: forward mic buffers directly (mono).
    private func startMicOnlyMode() {
        micTask = Task { [weak self] in
            guard let self else { return }
            for await buffer in self.mic.audioBuffers {
                self.bufferContinuation?.yield(buffer)
            }
        }
    }

    public func stopRecording() async {
        _isRecording = false

        flushTask?.cancel()
        flushTask = nil
        micTask?.cancel()
        micTask = nil
        systemTask?.cancel()
        systemTask = nil

        await mic.stopRecording()
        if hasSystemAudio {
            await system.stopRecording()
            flushDualBuffers()
        }

        lock.lock()
        micBuffer.removeAll()
        systemBuffer.removeAll()
        lock.unlock()

        hasSystemAudio = false
        bufferContinuation?.finish()
        setupBufferStream()
    }

    /// Interleave mic + system samples into a 2-channel non-interleaved PCM buffer.
    private func flushDualBuffers() {
        lock.lock()
        let micSamples = micBuffer
        let sysSamples = systemBuffer
        let frames = min(micSamples.count, sysSamples.count)
        if frames > 0 {
            micBuffer.removeFirst(frames)
            systemBuffer.removeFirst(frames)
        }
        lock.unlock()

        guard frames > 0 else { return }

        // Non-interleaved 2-channel: floatChannelData[0] = mic, floatChannelData[1] = system
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: config.sampleRate,
            channels: 2,
            interleaved: false
        ) else { return }

        guard let outBuffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: AVAudioFrameCount(frames)
        ) else { return }
        outBuffer.frameLength = AVAudioFrameCount(frames)

        guard let outData = outBuffer.floatChannelData else { return }
        let ch0 = outData[0] // mic
        let ch1 = outData[1] // system

        for i in 0..<frames {
            ch0[i] = micSamples[i]
            ch1[i] = sysSamples[i]
        }

        bufferContinuation?.yield(outBuffer)
    }
}
