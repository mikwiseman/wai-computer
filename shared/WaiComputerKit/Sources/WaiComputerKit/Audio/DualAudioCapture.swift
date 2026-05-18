#if os(macOS)
import Foundation
import AVFoundation
import os

private let dualLog = Logger(subsystem: "is.waiwai.computer.kit", category: "dual-audio")

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
    private var earlySystemAudioCheckTask: Task<Void, Never>?

    private let lock = NSLock()
    private let continuationLock: UnsafeMutablePointer<os_unfair_lock>
    private var micBuffer: [Float] = []
    private var systemBuffer: [Float] = []
    /// Whether system audio has ever received non-silent samples since recording started.
    public private(set) var systemAudioReceivedAny = false

    private var lastAudibleSystemAudioAt: Date?

    /// Whether system audio has stalled (no audible samples for multiple monitor intervals).
    public private(set) var systemAudioStalled = false

    static let audioPresenceThreshold: Float = 0.000_001

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
                self.appendMicrophoneSamples(samples)
            }
        }

        systemTask = Task { [weak self] in
            guard let self else { return }
            for await buffer in self.system.audioBuffers {
                guard let floatData = buffer.floatChannelData else { continue }
                let frames = Int(buffer.frameLength)
                let samples = Array(UnsafeBufferPointer(start: floatData[0], count: frames))
                let hasRealSystemAudio = Self.bufferContainsAudibleSamples(buffer)
                self.appendSystemSamples(samples, hasRealSystemAudio: hasRealSystemAudio)
            }
        }

        // Fast-path stall detection: if the CATap was created but is producing
        // pure silence (e.g. permission was denied, the running process has a
        // stale TCC cache, or the user's output device is a Bluetooth sink the
        // tap can't observe), surface the warning at 3 seconds instead of
        // waiting the usual ~6 seconds for the periodic flush-task detector.
        earlySystemAudioCheckTask = Task { [weak self] in
            guard let self else { return }
            let received = await self.system.waitForAudibleAudio(timeout: 3.0)
            if !received {
                dualLog.error("[Dual] System audio tap produced no audible samples within 3s — marking stalled. Likely causes: TCC denied, stale permission cache after grant, or output device (e.g. Bluetooth headphones) is not observable by CATap.")
                self.markSystemAudioStalled()
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
                    if self?.hasRecentSystemAudio() == false {
                        zeroSystemCount += 1
                    } else {
                        zeroSystemCount = 0
                    }

                    // Only surface a stall warning when system audio NEVER
                    // arrived. A mid-recording silence (meeting pause, user
                    // hits mute on the other end, etc.) is normal — surfacing
                    // "system audio not reaching" in that case would be a
                    // false positive that erodes trust in the warning.
                    if zeroSystemCount >= 2, self?.systemAudioReceivedAny == false {
                        self?.markSystemAudioStalled()
                        dualLog.error("[Dual] System audio never produced audible samples after \(zeroSystemCount * 3)s; microphone audio continues.")
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
                self.yieldBuffer(buffer)
            }
        }
    }

    public func stopRecording() async {
        _isRecording = false

        flushTask?.cancel()
        await flushTask?.value
        flushTask = nil
        earlySystemAudioCheckTask?.cancel()
        earlySystemAudioCheckTask = nil
        micTask?.cancel()
        micTask = nil
        systemTask?.cancel()
        systemTask = nil

        await mic.stopRecording()
        if hasSystemAudio {
            await system.stopRecording()
            flushDualBuffers()
        }

        resetBufferedState()

        hasSystemAudio = false
        finishBufferStream()
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
        let systemAudioUsable = systemAudioReceivedAny && !systemAudioStalled

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
                mono[i] = Self.monoMixedSample(
                    microphone: micSamples[i],
                    system: sysSamples[i],
                    hasSystemAudio: systemAudioUsable
                )
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

    static func bufferContainsAudibleSamples(_ buffer: AVAudioPCMBuffer) -> Bool {
        guard let floatData = buffer.floatChannelData else { return false }
        let frames = Int(buffer.frameLength)
        let channels = Int(buffer.format.channelCount)
        guard frames > 0, channels > 0 else { return false }

        for channel in 0..<channels {
            let samples = floatData[channel]
            for frame in 0..<frames where abs(samples[frame]) > audioPresenceThreshold {
                return true
            }
        }

        return false
    }

    static func monoMixedSample(microphone: Float, system: Float, hasSystemAudio: Bool) -> Float {
        guard hasSystemAudio else { return microphone }
        return (microphone + system) * 0.5
    }

    private func appendMicrophoneSamples(_ samples: [Float]) {
        lock.lock()
        micBuffer.append(contentsOf: samples)
        lock.unlock()
    }

    private func appendSystemSamples(_ samples: [Float], hasRealSystemAudio: Bool) {
        lock.lock()
        systemBuffer.append(contentsOf: samples)
        if hasRealSystemAudio {
            systemAudioReceivedAny = true
            lastAudibleSystemAudioAt = Date()
            systemAudioStalled = false
        }
        lock.unlock()
    }

    private func hasRecentSystemAudio() -> Bool {
        lock.lock()
        let lastAudibleAt = lastAudibleSystemAudioAt
        lock.unlock()

        guard let lastAudibleAt else { return false }
        return Date().timeIntervalSince(lastAudibleAt) < 4.0
    }

    private func markSystemAudioStalled() {
        lock.lock()
        systemAudioStalled = true
        lock.unlock()
    }

    private func resetBufferedState() {
        lock.lock()
        micBuffer.removeAll()
        systemBuffer.removeAll()
        systemAudioReceivedAny = false
        systemAudioStalled = false
        lastAudibleSystemAudioAt = nil
        lock.unlock()
    }

    private func yieldBuffer(_ buffer: AVAudioPCMBuffer) {
        os_unfair_lock_lock(continuationLock)
        bufferContinuation?.yield(buffer)
        os_unfair_lock_unlock(continuationLock)
    }

    private func finishBufferStream() {
        os_unfair_lock_lock(continuationLock)
        bufferContinuation?.finish()
        os_unfair_lock_unlock(continuationLock)
    }
}
#endif
