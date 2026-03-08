import Foundation
import AVFoundation
import os

private let dualLog = Logger(subsystem: "com.waicomputer.kit", category: "dual-audio")

/// Captures both microphone and system audio simultaneously, producing
/// 2-channel interleaved PCM buffers (ch0 = mic, ch1 = system audio).
///
/// If system audio capture fails (e.g. no permission on macOS < 14.2),
/// falls back to mic-only with silence on channel 2.
@available(macOS 14.2, *)
public final class DualAudioCapture: AudioCaptureProtocol, @unchecked Sendable {
    private let mic: MicrophoneCapture
    private let system: SystemAudioCapture
    private let config: AudioCaptureConfig

    private var bufferContinuation: AsyncStream<AVAudioPCMBuffer>.Continuation?
    public private(set) var audioBuffers: AsyncStream<AVAudioPCMBuffer>

    private var _isRecording = false
    public var isRecording: Bool { _isRecording }

    /// Whether system audio is active (false = mic-only mode)
    public private(set) var hasSystemAudio = false

    private var micTask: Task<Void, Never>?
    private var systemTask: Task<Void, Never>?

    /// Ring buffer for interleaving: holds latest mic/system chunks keyed by approximate timestamp
    private let lock = NSLock()
    private var micBuffer: [Float] = []
    private var systemBuffer: [Float] = []
    private var flushTask: Task<Void, Never>?

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

        // Try system audio (optional — may fail without permission)
        do {
            try await system.startRecording()
            hasSystemAudio = true
            dualLog.warning("[Dual] System audio started")
        } catch {
            hasSystemAudio = false
            dualLog.warning("[Dual] System audio unavailable: \(error.localizedDescription) — mic-only mode")
        }

        _isRecording = true

        // Forward mic buffers into our accumulator
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

        // Forward system audio buffers (if available)
        if hasSystemAudio {
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
        }

        // Periodic flush: interleave accumulated samples into 2-channel buffers
        let flushInterval = 0.16 // ~160ms, matching buffer size
        flushTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(flushInterval))
                guard !Task.isCancelled else { break }
                self?.flushBuffers()
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
        }

        // Flush any remaining samples
        flushBuffers()

        lock.lock()
        micBuffer.removeAll()
        systemBuffer.removeAll()
        lock.unlock()

        hasSystemAudio = false
        bufferContinuation?.finish()
        setupBufferStream()
    }

    /// Interleave mic + system samples into a 2-channel PCM buffer.
    private func flushBuffers() {
        lock.lock()
        let micSamples = micBuffer
        let sysSamples = systemBuffer
        // Use the shorter length to keep channels aligned
        let frames = hasSystemAudio ? min(micSamples.count, sysSamples.count) : micSamples.count
        if frames > 0 {
            micBuffer.removeFirst(min(frames, micBuffer.count))
            if hasSystemAudio {
                systemBuffer.removeFirst(min(frames, systemBuffer.count))
            }
        }
        lock.unlock()

        guard frames > 0 else { return }

        // Create 2-channel interleaved buffer
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: config.sampleRate,
            channels: 2,
            interleaved: true
        ) else { return }

        guard let outBuffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: AVAudioFrameCount(frames)
        ) else { return }
        outBuffer.frameLength = AVAudioFrameCount(frames)

        guard let outData = outBuffer.floatChannelData else { return }
        // For interleaved format, all data is in channel 0's pointer
        let dst = outData[0]

        for i in 0..<frames {
            dst[i * 2] = micSamples[i]           // channel 0 = mic
            dst[i * 2 + 1] = hasSystemAudio ? sysSamples[i] : 0.0  // channel 1 = system (or silence)
        }

        bufferContinuation?.yield(outBuffer)
    }
}
