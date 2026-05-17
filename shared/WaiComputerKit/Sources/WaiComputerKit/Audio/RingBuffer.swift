import Foundation
import AVFoundation

/// Thread-safe ring buffer of `AVAudioPCMBuffer` references.
///
/// Used by `AudioEngineHost` to keep the most recent ~500 ms of microphone
/// audio so that on push-to-talk we can prepend pre-roll to the outgoing
/// stream — eliminating the "first word dropped" symptom that plagues
/// cold-start dictation, especially over Bluetooth HFP where the A2DP→HFP
/// switch costs 200–500 ms before the mic actually wakes up.
///
/// The buffer keeps pointers to existing `AVAudioPCMBuffer`s — it does NOT
/// copy samples. Callers must not mutate the underlying buffer after pushing.
public final class PCMRingBuffer: @unchecked Sendable {
    private struct Slot {
        let buffer: AVAudioPCMBuffer
        let frames: AVAudioFrameCount
    }

    private let lock = NSLock()
    private var slots: [Slot] = []
    private var totalFrames: AVAudioFrameCount = 0
    private let capacityFrames: AVAudioFrameCount

    public init(capacityFrames: AVAudioFrameCount) {
        self.capacityFrames = capacityFrames
    }

    public func append(_ buffer: AVAudioPCMBuffer) {
        let frames = buffer.frameLength
        guard frames > 0 else { return }

        lock.lock()
        defer { lock.unlock() }

        slots.append(Slot(buffer: buffer, frames: frames))
        totalFrames += frames

        while totalFrames > capacityFrames, !slots.isEmpty {
            let dropped = slots.removeFirst()
            totalFrames -= dropped.frames
        }
    }

    /// Returns up to `limitFrames` of the most recent samples as a list of
    /// buffers in chronological order. Older buffers may be partially
    /// represented if the limit slices through them — in that case a copy
    /// of just the tail is created.
    public func snapshot(limitFrames: AVAudioFrameCount) -> [AVAudioPCMBuffer] {
        lock.lock()
        defer { lock.unlock() }

        guard !slots.isEmpty else { return [] }

        var taken: AVAudioFrameCount = 0
        var result: [AVAudioPCMBuffer] = []
        for slot in slots.reversed() {
            if taken + slot.frames <= limitFrames {
                result.insert(slot.buffer, at: 0)
                taken += slot.frames
            } else {
                let needed = limitFrames - taken
                if needed == 0 { break }
                if let tail = sliceTail(of: slot.buffer, frames: needed) {
                    result.insert(tail, at: 0)
                    taken += needed
                }
                break
            }
        }
        return result
    }

    public func clear() {
        lock.lock()
        defer { lock.unlock() }
        slots.removeAll(keepingCapacity: true)
        totalFrames = 0
    }

    public var bufferedFrames: AVAudioFrameCount {
        lock.lock()
        defer { lock.unlock() }
        return totalFrames
    }

    private func sliceTail(of buffer: AVAudioPCMBuffer, frames: AVAudioFrameCount) -> AVAudioPCMBuffer? {
        guard let format = buffer.format as AVAudioFormat? else { return nil }
        guard let copy = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else { return nil }
        copy.frameLength = frames

        let total = buffer.frameLength
        let offset = total > frames ? total - frames : 0

        let channelCount = Int(format.channelCount)
        if let src = buffer.floatChannelData, let dst = copy.floatChannelData {
            for ch in 0..<channelCount {
                memcpy(dst[ch], src[ch].advanced(by: Int(offset)), Int(frames) * MemoryLayout<Float>.size)
            }
        } else if let src = buffer.int16ChannelData, let dst = copy.int16ChannelData {
            for ch in 0..<channelCount {
                memcpy(dst[ch], src[ch].advanced(by: Int(offset)), Int(frames) * MemoryLayout<Int16>.size)
            }
        } else {
            return nil
        }
        return copy
    }
}
