import XCTest
import AVFoundation
@testable import WaiComputerKit

final class PCMRingBufferTests: XCTestCase {

    private let format = AVAudioFormat(
        commonFormat: .pcmFormatFloat32,
        sampleRate: 16_000,
        channels: 1,
        interleaved: false
    )!

    // MARK: - Empty / init

    func testInitEmpty() {
        let ring = PCMRingBuffer(capacityFrames: 8_000)
        XCTAssertEqual(ring.bufferedFrames, 0)
        XCTAssertTrue(ring.snapshot(limitFrames: 1000).isEmpty)
    }

    func testSnapshotEmptyReturnsEmptyArray() {
        let ring = PCMRingBuffer(capacityFrames: 8_000)
        XCTAssertTrue(ring.snapshot(limitFrames: 4_000).isEmpty)
    }

    // MARK: - Append / counter

    func testAppendUpdatesBufferedFrames() {
        let ring = PCMRingBuffer(capacityFrames: 10_000)
        ring.append(makeBuffer(frames: 1_000, value: 0.1))
        XCTAssertEqual(ring.bufferedFrames, 1_000)
        ring.append(makeBuffer(frames: 2_000, value: 0.2))
        XCTAssertEqual(ring.bufferedFrames, 3_000)
    }

    func testAppendZeroFrameBufferIsIgnored() {
        let ring = PCMRingBuffer(capacityFrames: 10_000)
        let empty = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 100)!
        empty.frameLength = 0
        ring.append(empty)
        XCTAssertEqual(ring.bufferedFrames, 0)
    }

    // MARK: - Capacity / wraparound

    func testOverflowDropsOldestSlots() {
        let ring = PCMRingBuffer(capacityFrames: 3_000)
        ring.append(makeBuffer(frames: 1_000, value: 0.1))
        ring.append(makeBuffer(frames: 1_000, value: 0.2))
        ring.append(makeBuffer(frames: 1_000, value: 0.3))
        XCTAssertEqual(ring.bufferedFrames, 3_000)

        ring.append(makeBuffer(frames: 1_000, value: 0.4))
        XCTAssertEqual(ring.bufferedFrames, 3_000, "still at cap after a 4th 1000-frame buffer")

        // The oldest (0.1) should be evicted; newest snapshot should yield 0.2, 0.3, 0.4
        let snap = ring.snapshot(limitFrames: 3_000)
        XCTAssertEqual(snap.count, 3)
        XCTAssertEqual(firstSample(snap[0]), 0.2, accuracy: 1e-6)
        XCTAssertEqual(firstSample(snap[1]), 0.3, accuracy: 1e-6)
        XCTAssertEqual(firstSample(snap[2]), 0.4, accuracy: 1e-6)
    }

    func testOverflowEvictsMultipleSlotsWhenSingleBufferIsLarger() {
        let ring = PCMRingBuffer(capacityFrames: 2_000)
        ring.append(makeBuffer(frames: 500, value: 0.1))
        ring.append(makeBuffer(frames: 500, value: 0.2))
        ring.append(makeBuffer(frames: 500, value: 0.3))
        ring.append(makeBuffer(frames: 500, value: 0.4))
        XCTAssertEqual(ring.bufferedFrames, 2_000)

        // Append a single 1500-frame buffer — should evict 0.1 and 0.2 (total 1000),
        // leaving 0.3 + 0.4 + new buffer = 500 + 500 + 1500 = 2500, then evict 0.3.
        ring.append(makeBuffer(frames: 1_500, value: 0.9))
        XCTAssertEqual(ring.bufferedFrames, 2_000, "ring stays at capacity after eviction")
    }

    // MARK: - Snapshot

    func testSnapshotReturnsAllWhenLimitExceedsBuffered() {
        let ring = PCMRingBuffer(capacityFrames: 10_000)
        ring.append(makeBuffer(frames: 500, value: 0.1))
        ring.append(makeBuffer(frames: 500, value: 0.2))

        let snap = ring.snapshot(limitFrames: 10_000)
        XCTAssertEqual(snap.count, 2)
        XCTAssertEqual(firstSample(snap[0]), 0.1, accuracy: 1e-6)
        XCTAssertEqual(firstSample(snap[1]), 0.2, accuracy: 1e-6)
    }

    func testSnapshotSlicesTailOfPartiallyConsumedBuffer() {
        let ring = PCMRingBuffer(capacityFrames: 10_000)
        // 1000-frame buffer; ask for just 400 of them — should yield a tail slice.
        ring.append(makeRampBuffer(frames: 1_000))

        let snap = ring.snapshot(limitFrames: 400)
        XCTAssertEqual(snap.count, 1)
        XCTAssertEqual(Int(snap[0].frameLength), 400)
        // Tail slice: original buffer is ramp(0..999), tail 400 = frames 600..999
        let data = snap[0].floatChannelData!
        XCTAssertEqual(data[0][0], 600.0 / 1000.0, accuracy: 1e-3)
        XCTAssertEqual(data[0][399], 999.0 / 1000.0, accuracy: 1e-3)
    }

    func testSnapshotZeroLimitReturnsEmpty() {
        let ring = PCMRingBuffer(capacityFrames: 10_000)
        ring.append(makeBuffer(frames: 1_000, value: 0.1))
        XCTAssertTrue(ring.snapshot(limitFrames: 0).isEmpty)
    }

    func testSnapshotChronologicalOrder() {
        let ring = PCMRingBuffer(capacityFrames: 10_000)
        ring.append(makeBuffer(frames: 100, value: 0.1))
        ring.append(makeBuffer(frames: 100, value: 0.2))
        ring.append(makeBuffer(frames: 100, value: 0.3))

        let snap = ring.snapshot(limitFrames: 300)
        XCTAssertEqual(firstSample(snap[0]), 0.1, accuracy: 1e-6)
        XCTAssertEqual(firstSample(snap[1]), 0.2, accuracy: 1e-6)
        XCTAssertEqual(firstSample(snap[2]), 0.3, accuracy: 1e-6)
    }

    // MARK: - Clear

    func testClearResetsState() {
        let ring = PCMRingBuffer(capacityFrames: 10_000)
        ring.append(makeBuffer(frames: 500, value: 0.1))
        ring.append(makeBuffer(frames: 500, value: 0.2))
        ring.clear()
        XCTAssertEqual(ring.bufferedFrames, 0)
        XCTAssertTrue(ring.snapshot(limitFrames: 10_000).isEmpty)
    }

    // MARK: - Thread safety

    func testConcurrentAppendAndSnapshotDoesNotCrash() {
        let ring = PCMRingBuffer(capacityFrames: 50_000)
        let group = DispatchGroup()
        let queue = DispatchQueue.global()

        for _ in 0..<8 {
            group.enter()
            queue.async {
                for _ in 0..<200 {
                    ring.append(self.makeBuffer(frames: 100, value: 0.5))
                }
                group.leave()
            }
        }
        for _ in 0..<4 {
            group.enter()
            queue.async {
                for _ in 0..<200 {
                    _ = ring.snapshot(limitFrames: 5_000)
                }
                group.leave()
            }
        }
        group.wait()
        // Just don't crash — buffered frames bounded by capacity
        XCTAssertLessThanOrEqual(ring.bufferedFrames, 50_000)
    }

    // MARK: - Helpers

    private func makeBuffer(frames: AVAudioFrameCount, value: Float) -> AVAudioPCMBuffer {
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames)!
        buffer.frameLength = frames
        let channelData = buffer.floatChannelData!
        for i in 0..<Int(frames) {
            channelData[0][i] = value
        }
        return buffer
    }

    private func makeRampBuffer(frames: AVAudioFrameCount) -> AVAudioPCMBuffer {
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames)!
        buffer.frameLength = frames
        let channelData = buffer.floatChannelData!
        for i in 0..<Int(frames) {
            channelData[0][i] = Float(i) / Float(frames)
        }
        return buffer
    }

    private func firstSample(_ buffer: AVAudioPCMBuffer) -> Float {
        return buffer.floatChannelData![0][0]
    }
}
