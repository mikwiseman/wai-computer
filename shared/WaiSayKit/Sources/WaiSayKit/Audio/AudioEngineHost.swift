import Foundation
import AVFoundation
import os

private let hostLog = Logger(subsystem: "com.waisay.kit", category: "audioEngineHost")

/// Process-singleton AVAudioEngine manager that follows the Wispr Flow / Sebsto-Wispr
/// pre-warm pattern. The engine is started **once** after permission grant and
/// stays running for the lifetime of the dictation feature. Per-press dictation
/// sessions acquire a `Lease` that installs the input tap, snapshots the
/// pre-roll buffer, and exposes a stream of resampled 16 kHz mono Float32
/// PCM buffers.
///
/// Why this matters:
/// - Repeatedly `engine.start()` / `engine.stop()` on macOS 14+ causes the
///   audio HAL to enter a degraded state after 3–5 cycles, manifesting as
///   `kAudioUnitErr_FailedInitialization` (-10875) or silent buffers.
/// - Bluetooth HFP (AirPods) takes 200–500 ms to switch from A2DP playback
///   profile to mono call-quality profile when the mic activates. With the
///   engine already running, this transition has already happened before
///   the user presses the hotkey — no first-word loss.
/// - The pre-roll buffer keeps the most recent 500 ms of audio so even a
///   user who starts speaking at the same instant they press the hotkey
///   gets a complete transcript.
public actor AudioEngineHost {
    public static let shared = AudioEngineHost()

    private let engine: AVAudioEngine
    private let preRoll: PCMRingBuffer
    /// 16 kHz mono Float32 — the format we emit to consumers.
    private let outputFormat: AVAudioFormat
    private var resampler: PCMResampler?
    private var preWarmed = false
    private var activeLease: UUID?
    private var liveContinuation: AsyncStream<AVAudioPCMBuffer>.Continuation?
    /// Frames currently in the pre-roll ring at 16 kHz mono. Caps memory.
    public static let preRollFrames: AVAudioFrameCount = 8_000  // 500 ms @ 16 kHz

    private init() {
        self.engine = AVAudioEngine()
        self.preRoll = PCMRingBuffer(capacityFrames: Self.preRollFrames)
        self.outputFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 16_000,
            channels: 1,
            interleaved: false
        )!
    }

    /// Start the engine and begin capturing into the pre-roll ring buffer.
    /// Idempotent: subsequent calls are no-ops.
    public func prewarm() async throws {
        guard !preWarmed else { return }

        let input = engine.inputNode
        let nativeFormat = input.outputFormat(forBus: 0)
        hostLog.info("[Host] Pre-warming engine — native \(nativeFormat.sampleRate)Hz \(nativeFormat.channelCount)ch")

        guard let resampler = PCMResampler(source: nativeFormat) else {
            throw AudioCaptureError.invalidFormat
        }
        self.resampler = resampler

        // Defensive: remove any stale tap from a prior failed prewarm() so
        // a retry doesn't crash with "Already attached" (NSInvalidArgumentException
        // — `installTap` crashes if a tap already exists on the bus).
        // `removeTap` on a clean bus is a no-op.
        input.removeTap(onBus: 0)

        // Install a tap with `format: nil` (native format). On macOS this is
        // the only supported configuration — passing a different format
        // throws an exception. Resampling happens manually below.
        input.installTap(onBus: 0, bufferSize: 4096, format: nil) { [weak self] buffer, _ in
            // The tap callback runs on a real-time audio thread. Hop into the
            // actor for state mutation. `Task` is fine because the buffer is
            // captured by reference; AVAudioEngine reuses the storage so we
            // must convert immediately.
            guard let self else { return }
            let copy = Self.copy(buffer: buffer)
            Task { await self.handleTapBuffer(copy) }
        }

        engine.prepare()
        do {
            try engine.start()
        } catch {
            // Roll back the tap so the next retry can install cleanly.
            input.removeTap(onBus: 0)
            self.resampler = nil
            hostLog.error("[Host] engine.start() failed — tap removed for retry safety")
            throw error
        }
        preWarmed = true
        hostLog.info("[Host] Engine started")
    }

    /// Tear down the engine and remove the tap. Only call on app quit / when
    /// dictation feature is disabled — never between sessions.
    public func teardown() {
        guard preWarmed else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        preRoll.clear()
        liveContinuation?.finish()
        liveContinuation = nil
        activeLease = nil
        preWarmed = false
        hostLog.info("[Host] Engine stopped")
    }

    /// Acquire an exclusive recording lease. Returns the pre-roll snapshot
    /// (last ~500 ms) plus a stream of subsequent live buffers. Only one
    /// lease may be active at a time; concurrent acquisitions throw.
    public func lease() throws -> Lease {
        guard preWarmed else { throw AudioCaptureError.notStarted }
        guard activeLease == nil else { throw AudioCaptureError.leaseInUse }

        let id = UUID()
        activeLease = id

        let preRollBuffers = preRoll.snapshot(limitFrames: Self.preRollFrames)
        let (stream, continuation) = AsyncStream.makeStream(of: AVAudioPCMBuffer.self)
        liveContinuation = continuation

        return Lease(
            id: id,
            preRoll: preRollBuffers,
            buffers: stream,
            outputFormat: outputFormat
        )
    }

    /// Release a previously acquired lease. The pre-roll continues filling
    /// in the background so the next session also gets fresh pre-roll.
    public func release(_ lease: Lease) {
        guard activeLease == lease.id else { return }
        liveContinuation?.finish()
        liveContinuation = nil
        activeLease = nil
    }

    /// Whether the engine is running. Used by tests / instrumentation.
    public var isPrewarmed: Bool { preWarmed }

    // MARK: - Private

    private func handleTapBuffer(_ buffer: AVAudioPCMBuffer) {
        guard let resampled = resampler?.convert(buffer) else { return }

        // Always feed the pre-roll so a session starting in 50 ms has fresh
        // context.
        preRoll.append(resampled)

        // Fan out to active lease, if any.
        if activeLease != nil, let cont = liveContinuation {
            cont.yield(resampled)
        }
    }

    private static func copy(buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer {
        guard let dst = AVAudioPCMBuffer(pcmFormat: buffer.format, frameCapacity: buffer.frameLength) else {
            return buffer
        }
        dst.frameLength = buffer.frameLength
        let channelCount = Int(buffer.format.channelCount)
        let bytesPerFrame = Int(buffer.format.streamDescription.pointee.mBytesPerFrame)

        if buffer.format.commonFormat == .pcmFormatFloat32,
           let src = buffer.floatChannelData, let out = dst.floatChannelData {
            for ch in 0..<channelCount {
                memcpy(out[ch], src[ch], Int(buffer.frameLength) * MemoryLayout<Float>.size)
            }
        } else if buffer.format.commonFormat == .pcmFormatInt16,
                  let src = buffer.int16ChannelData, let out = dst.int16ChannelData {
            for ch in 0..<channelCount {
                memcpy(out[ch], src[ch], Int(buffer.frameLength) * MemoryLayout<Int16>.size)
            }
        } else if let src = buffer.audioBufferList.pointee.mBuffers.mData,
                  let out = dst.audioBufferList.pointee.mBuffers.mData {
            memcpy(out, src, Int(buffer.frameLength) * bytesPerFrame)
        }
        return dst
    }
}

public extension AudioEngineHost {
    /// An exclusive recording session over the shared AVAudioEngine.
    /// Drop this and call `release(_:)` when done.
    ///
    /// `@unchecked Sendable` because AVAudioPCMBuffer is not yet Sendable in
    /// the AVFAudio overlay; we hand-control concurrency via the actor.
    struct Lease: @unchecked Sendable {
        public let id: UUID
        /// Pre-roll buffers captured BEFORE the hotkey was pressed (500 ms).
        public let preRoll: [AVAudioPCMBuffer]
        /// Live buffers captured AFTER the hotkey was pressed.
        public let buffers: AsyncStream<AVAudioPCMBuffer>
        public let outputFormat: AVAudioFormat
    }
}

public enum AudioEngineHostError: Error {
    case engineFailedToStart(OSStatus)
}
