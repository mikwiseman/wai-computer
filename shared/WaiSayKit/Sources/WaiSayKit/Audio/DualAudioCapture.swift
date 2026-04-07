#if os(macOS)
import Foundation
import AVFoundation
import os

private let dualLog = Logger(subsystem: "com.waisay.kit", category: "dual-audio")

/// Captures both microphone and system audio simultaneously.
///
/// When `mixToMono` is `true` (default), both sources are averaged into a single
/// mono channel. The active transcription provider can then use diarization or
/// speaker segmentation to distinguish speakers in group calls.
///
/// When `mixToMono` is `false`, produces 2-channel non-interleaved PCM buffers
/// (ch0 = mic, ch1 = system audio) for provider-side multichannel transcription.
///
/// When system audio is unavailable, produces mono buffers from mic only.
@available(macOS 14.2, *)
public final class DualAudioCapture: AudioCaptureProtocol, @unchecked Sendable {
    private let mic: MicrophoneCapture
    private let system: SystemAudioCapture
    private let config: AudioCaptureConfig

    /// When `true`, mic and system audio are mixed into a single mono channel
    /// so the speech provider can apply diarization or speaker segmentation.
    /// When `false`, produces 2-channel non-interleaved buffers for multichannel mode.
    public let mixToMono: Bool

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
    private let continuationLock: UnsafeMutablePointer<os_unfair_lock>
    private var micBuffer: [Float] = []
    private var systemBuffer: [Float] = []
    /// Whether system audio has ever received any samples since recording started.
    public private(set) var systemAudioReceivedAny = false

    /// Whether system audio has stalled (no samples received for >3 seconds)
    public private(set) var systemAudioStalled = false

    public init(config: AudioCaptureConfig = .default, mixToMono: Bool = true) {
        self.config = config
        self.mixToMono = mixToMono
        self.mic = MicrophoneCapture(config: config)
        self.system = SystemAudioCapture(config: config)
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
            dualLog.warning("[Dual] System audio started — \(self.mixToMono ? "mono-mix mode (diarization)" : "2-channel mode (multichannel)")")
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
                self.systemAudioReceivedAny = true
                self.systemAudioStalled = false
                self.lock.unlock()
            }
        }

        flushTask = Task { [weak self] in
            var flushCount = 0
            var zeroSystemCount = 0
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(0.16))
                guard !Task.isCancelled else { break }
                self?.flushDualBuffers()
                flushCount += 1

                // Stall detection: check every ~3 seconds (18 flushes × 160ms)
                if flushCount % 18 == 0 {
                    self?.lock.lock()
                    let sysEmpty = self?.systemBuffer.isEmpty ?? true
                    let receivedAny = self?.systemAudioReceivedAny ?? false
                    self?.lock.unlock()

                    if sysEmpty && !receivedAny {
                        zeroSystemCount += 1
                    } else {
                        zeroSystemCount = 0
                    }

                    if zeroSystemCount >= 2 {
                        self?.systemAudioStalled = true
                        dualLog.error("[Dual] ⚠️ System audio stalled — no samples received after \(zeroSystemCount * 3)s. Other participants will NOT be transcribed.")
                    }
                }
            }
        }
    }

    /// Mic-only mode: forward mic buffers directly (mono).
    private func startMicOnlyMode() {
        micTask = Task { [weak self] in
            guard let self else { return }
            for await buffer in self.mic.audioBuffers {
                os_unfair_lock_lock(self.continuationLock)
                self.bufferContinuation?.yield(buffer)
                os_unfair_lock_unlock(self.continuationLock)
            }
        }
    }

    public func stopRecording() async {
        _isRecording = false

        flushTask?.cancel()
        await flushTask?.value
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
        os_unfair_lock_lock(continuationLock)
        bufferContinuation?.finish()
        os_unfair_lock_unlock(continuationLock)
        setupBufferStream()
    }

    deinit {
        continuationLock.deinitialize(count: 1)
        continuationLock.deallocate()
    }

    /// Flush accumulated mic + system samples into a 2-channel non-interleaved PCM buffer.
    /// Uses the minimum of both buffers when both have data, to keep channels in sync.
    /// Falls back to mic-only with silence padding if system audio stalls.
    private func flushDualBuffers() {
        lock.lock()
        let micCount = micBuffer.count
        let sysCount = systemBuffer.count

        // Minimum flush size: 80ms at target sample rate (prevents tiny flushes)
        let minFlushSize = Int(config.sampleRate * 0.08)

        // When both streams have enough data, use the minimum to stay in sync.
        // If system audio is stalling (has zero samples), use mic with silence padding
        // to avoid blocking the entire pipeline.
        let frames: Int
        if sysCount >= minFlushSize && micCount >= minFlushSize {
            // Both have enough — use minimum to keep in sync
            frames = min(micCount, sysCount)
        } else if micCount >= minFlushSize && sysCount == 0 {
            // System audio stalled — flush mic with silence padding
            // but cap at 1 second to avoid huge silent system channel buffers
            frames = min(micCount, Int(config.sampleRate))
        } else if micCount >= minFlushSize {
            // System has some data but less than minimum — use what's available
            frames = min(micCount, max(sysCount, minFlushSize))
        } else {
            // Not enough mic data yet
            lock.unlock()
            return
        }

        guard frames > 0 else {
            lock.unlock()
            return
        }

        let micSamples = Array(micBuffer.prefix(frames))
        micBuffer.removeFirst(frames)

        let sysSamples: [Float]
        if sysCount >= frames {
            sysSamples = Array(systemBuffer.prefix(frames))
            systemBuffer.removeFirst(frames)
        } else if sysCount > 0 {
            // System audio has fewer samples — take what's available, pad rest with silence
            sysSamples = Array(systemBuffer) + Array(repeating: 0.0, count: frames - sysCount)
            systemBuffer.removeAll()
        } else {
            // No system audio at all — all silence
            sysSamples = Array(repeating: 0.0, count: frames)
        }

        let continuation = bufferContinuation
        lock.unlock()

        if frames % 16000 == 0 || frames < 100 || (sysCount == 0 && micCount > 0) {
            dualLog.warning("[Dual] flush: \(frames) frames (mic=\(micCount), sys=\(sysCount)\(sysCount == 0 ? " ⚠️ NO SYSTEM AUDIO" : ""), mode=\(self.mixToMono ? "mono-mix" : "multichannel"))")
        }

        if mixToMono {
            // Mono mix: average mic + system audio into a single channel.
            // The speech provider handles diarization or speaker segmentation.
            guard let format = AVAudioFormat(
                commonFormat: .pcmFormatFloat32,
                sampleRate: config.sampleRate,
                channels: 1,
                interleaved: false
            ) else { return }

            guard let outBuffer = AVAudioPCMBuffer(
                pcmFormat: format,
                frameCapacity: AVAudioFrameCount(frames)
            ) else { return }
            outBuffer.frameLength = AVAudioFrameCount(frames)

            guard let outData = outBuffer.floatChannelData else { return }
            let mono = outData[0]

            for i in 0..<frames {
                mono[i] = (micSamples[i] + sysSamples[i]) * 0.5
            }

            os_unfair_lock_lock(continuationLock)
            continuation?.yield(outBuffer)
            os_unfair_lock_unlock(continuationLock)
        } else {
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

            os_unfair_lock_lock(continuationLock)
            continuation?.yield(outBuffer)
            os_unfair_lock_unlock(continuationLock)
        }
    }
}
#endif
