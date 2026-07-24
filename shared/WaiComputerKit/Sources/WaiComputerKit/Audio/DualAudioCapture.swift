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
@available(macOS 14.2, *)
public final class DualAudioCapture: AudioCaptureProtocol, @unchecked Sendable {
    private let mic: any AudioCaptureProtocol
    private let system: any SystemAudioCaptureProtocol
    private let config: AudioCaptureConfig

    /// When `true`, mic and system audio are mixed into a single mono channel
    /// so the speech provider can apply diarization or speaker segmentation.
    /// When `false`, produces 2-channel non-interleaved buffers for multichannel mode.
    public let mixToMono: Bool

    private var bufferContinuation: AsyncStream<AVAudioPCMBuffer>.Continuation?
    public private(set) var audioBuffers: AsyncStream<AVAudioPCMBuffer>

    private var _isRecording = false
    public var isRecording: Bool { _isRecording }
    public var isPaused: Bool {
        lock.lock()
        defer { lock.unlock() }
        return _isPaused
    }
    private var _isPaused = false

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
    /// Frame-clock tracker of local (mic) speech, fed pre-mix so the owner
    /// stays identifiable even in mono-mix mode. Guarded by `lock`.
    private var localSpeechTracker: LocalSpeechTracker?
    /// Whether system audio has delivered any buffers since recording started.
    public private(set) var systemAudioStreamActive = false

    /// Whether system audio has ever received non-silent samples since recording started.
    public private(set) var systemAudioReceivedAny = false

    private var lastSystemBufferAt: Date?

    /// Whether system audio has stalled (no buffers for multiple monitor intervals).
    public private(set) var systemAudioStalled = false

    /// Thread-safe health snapshot for owners that must reject silent
    /// mic-only degradation before finalizing a dual-source session.
    public var isSystemAudioStreamHealthy: Bool {
        lock.lock()
        defer { lock.unlock() }
        guard systemAudioStreamActive,
              !systemAudioStalled,
              let lastSystemBufferAt else {
            return false
        }
        // The tap normally delivers buffers continuously, including silence.
        // A recent buffer is therefore required at finalization; otherwise a
        // route/TCC failure near the end could predate the slower stall monitor.
        return Date().timeIntervalSince(lastSystemBufferAt) < 1.0
    }

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

    /// Build a dual capture around an already-running microphone stream.
    ///
    /// Dictation uses this initializer with `AudioEngineHost.Lease.buffers`.
    /// That preserves the process-wide microphone engine and its pre-roll
    /// instead of starting the per-session `MicrophoneCapture` that previously
    /// destabilized the macOS audio HAL after repeated dictation presses.
    ///
    /// The caller owns the microphone stream and must release its lease after
    /// `stopRecording()`. This capture owns only the system-audio tap.
    public convenience init(
        liveMicrophoneBuffers: AsyncStream<AVAudioPCMBuffer>,
        config: AudioCaptureConfig = .default,
        mixToMono: Bool = true
    ) {
        self.init(
            config: config,
            mixToMono: mixToMono,
            mic: LiveMicrophoneStreamCapture(audioBuffers: liveMicrophoneBuffers),
            system: SystemAudioCapture(config: config)
        )
    }

    init(
        config: AudioCaptureConfig = .default,
        mixToMono: Bool = true,
        mic: any AudioCaptureProtocol,
        system: any SystemAudioCaptureProtocol
    ) {
        self.config = config
        self.mixToMono = mixToMono
        self.mic = mic
        self.system = system
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

        do {
            try await system.startRecording()
            hasSystemAudio = true
            dualLog.warning("[Dual] System audio started — \(self.mixToMono ? "mono-mix mode (diarization)" : "2-channel mode (multichannel)")")
        } catch {
            hasSystemAudio = false
            await mic.stopRecording()
            dualLog.error("[Dual] System audio unavailable: \(error.localizedDescription, privacy: .public)")
            throw DualAudioCaptureError.systemAudioUnavailable(error.localizedDescription)
        }

        _isRecording = true
        setPaused(false)
        resetLocalSpeechTracker()
        startDualMode()
    }

    /// Merged `[start_ms, end_ms]` intervals of local-mic speech for the
    /// capture sidecar. Call after `stopRecording()`; drains the tracker.
    public func drainLocalSpeechIntervalsMs() -> [[Int]] {
        lock.lock()
        defer { lock.unlock() }
        guard var tracker = localSpeechTracker else { return [] }
        localSpeechTracker = nil
        return tracker.finish()
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

        // Fast-path stall detection: surface a warning only if the tap produces
        // no buffers. Silent buffers are valid when nothing is playing yet.
        earlySystemAudioCheckTask = Task { [weak self] in
            guard let self else { return }
            let received = await self.system.waitForAudioBuffers(timeout: 3.0)
            if self.isPaused { return }
            if !received {
                dualLog.error("[Dual] System audio tap produced no buffers within 3s — marking stalled.")
                self.markSystemAudioStalled()
            }
        }

        flushTask = Task { [weak self] in
            var flushCount = 0
            var zeroSystemCount = 0
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(0.16))
                guard !Task.isCancelled else { break }
                guard self?.isPaused == false else { continue }
                self?.flushDualBuffers()
                flushCount += 1

                // Stall detection: check every ~3 seconds (18 flushes × 160ms)
                if flushCount % 18 == 0 {
                    if self?.hasRecentSystemAudioBuffer() == false {
                        zeroSystemCount += 1
                    } else {
                        zeroSystemCount = 0
                    }

                    // Only surface a stall warning when system audio buffers
                    // are not arriving. Mid-recording silence still delivers
                    // buffers and is normal.
                    if zeroSystemCount >= 2 {
                        self?.markSystemAudioStalled()
                        dualLog.error("[Dual] System audio produced no buffers for \(zeroSystemCount * 3)s.")
                    }
                }
            }
        }
    }

    public func pauseRecording() async throws {
        guard _isRecording, !isPaused else { return }

        flushDualBuffers()
        setPaused(true)
        if hasSystemAudio {
            do {
                try await system.pauseRecording()
            } catch {
                setPaused(false)
                throw error
            }
        }
        do {
            try await mic.pauseRecording()
        } catch {
            setPaused(false)
            if hasSystemAudio {
                try? await system.resumeRecording()
            }
            throw error
        }

        dualLog.info("[Dual] Paused recording")
    }

    public func resumeRecording() async throws {
        guard _isRecording, isPaused else { return }

        do {
            try await mic.resumeRecording()
            if hasSystemAudio {
                try await system.resumeRecording()
            }
        } catch {
            try? await mic.pauseRecording()
            if hasSystemAudio {
                try? await system.pauseRecording()
            }
            throw error
        }

        setPaused(false)
        dualLog.info("[Dual] Resumed recording")
    }

    public func stopRecording() async {
        _isRecording = false
        setPaused(false)

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
    /// Pads the system channel with silence if an already-started system stream stalls.
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

        localSpeechTracker?.ingest(
            mic: micSamples,
            system: systemAudioUsable ? sysSamples : []
        )
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
        guard !_isPaused else {
            lock.unlock()
            return
        }
        micBuffer.append(contentsOf: samples)
        lock.unlock()
    }

    private func appendSystemSamples(_ samples: [Float], hasRealSystemAudio: Bool) {
        lock.lock()
        guard !_isPaused else {
            lock.unlock()
            return
        }
        systemBuffer.append(contentsOf: samples)
        systemAudioStreamActive = true
        lastSystemBufferAt = Date()
        // `systemAudioStalled` means buffers stopped arriving. Any new buffer,
        // including a valid silent one between speakers, proves the tap has
        // recovered and must clear the stale warning.
        systemAudioStalled = false
        if hasRealSystemAudio {
            systemAudioReceivedAny = true
        }
        lock.unlock()
    }

    private func hasRecentSystemAudioBuffer() -> Bool {
        lock.lock()
        let lastBufferAt = lastSystemBufferAt
        lock.unlock()

        guard let lastBufferAt else { return false }
        return Date().timeIntervalSince(lastBufferAt) < 4.0
    }

    private func setPaused(_ paused: Bool) {
        lock.lock()
        _isPaused = paused
        if !paused {
            lastSystemBufferAt = Date()
        }
        lock.unlock()
    }

    private func resetLocalSpeechTracker() {
        lock.lock()
        localSpeechTracker = LocalSpeechTracker(sampleRate: config.sampleRate)
        lock.unlock()
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
        systemAudioStreamActive = false
        systemAudioReceivedAny = false
        systemAudioStalled = false
        lastSystemBufferAt = nil
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

@available(macOS 14.2, *)
private final class LiveMicrophoneStreamCapture: AudioCaptureProtocol, @unchecked Sendable {
    let audioBuffers: AsyncStream<AVAudioPCMBuffer>
    private(set) var isRecording = false
    private(set) var isPaused = false

    init(audioBuffers: AsyncStream<AVAudioPCMBuffer>) {
        self.audioBuffers = audioBuffers
    }

    func startRecording() async throws {
        isRecording = true
        isPaused = false
    }

    func pauseRecording() async throws {
        guard isRecording else { return }
        isPaused = true
    }

    func resumeRecording() async throws {
        guard isRecording else { return }
        isPaused = false
    }

    func stopRecording() async {
        isRecording = false
        isPaused = false
    }
}

@available(macOS 14.2, *)
protocol SystemAudioCaptureProtocol: AudioCaptureProtocol {
    func waitForAudioBuffers(timeout: TimeInterval) async -> Bool
}

@available(macOS 14.2, *)
extension SystemAudioCapture: SystemAudioCaptureProtocol {}

public enum DualAudioCaptureError: Error, LocalizedError, Sendable {
    case systemAudioUnavailable(String)

    public var errorDescription: String? {
        switch self {
        case .systemAudioUnavailable:
            return "System audio capture could not start. Complete System Audio setup in onboarding or enable WaiComputer in System Settings."
        }
    }
}
#endif
