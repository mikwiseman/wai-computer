import AVFoundation
import XCTest
@testable import WaiComputerKit

/// The realtime perf commit made PCMResampler reuse one AVAudioConverter across
/// calls (with reset()). If that reuse zeroes/empties output after the first
/// chunk, EVERY dictation goes silent → "Слушаем" with no words. This pins it.
final class PCMResamplerReuseTests: XCTestCase {
    private func sineChunk(_ source: AVAudioFormat, frames: AVAudioFrameCount, hz: Float) -> AVAudioPCMBuffer {
        let buf = AVAudioPCMBuffer(pcmFormat: source, frameCapacity: frames)!
        buf.frameLength = frames
        let ch = buf.floatChannelData![0]
        for i in 0..<Int(frames) {
            ch[i] = sin(2 * .pi * hz * Float(i) / Float(source.sampleRate)) * 0.5
        }
        return buf
    }

    private func energy(_ buf: AVAudioPCMBuffer) -> Float {
        guard let ch = buf.floatChannelData?[0] else { return 0 }
        var e: Float = 0
        for i in 0..<Int(buf.frameLength) { e += abs(ch[i]) }
        return e
    }

    func testReusedConverterStaysNonSilentAcrossChunks() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32, sampleRate: 48_000, channels: 1, interleaved: false
        )!
        let resampler = try XCTUnwrap(PCMResampler(source: source, targetSampleRate: 16_000, targetChannelCount: 1))

        for chunk in 0..<6 {
            let input = sineChunk(source, frames: 4_096, hz: 440)
            let out = try XCTUnwrap(resampler.convert(input), "chunk \(chunk): convert returned nil")
            XCTAssertGreaterThan(out.frameLength, 0, "chunk \(chunk): empty output")
            let e = energy(out)
            XCTAssertGreaterThan(e, 1.0, "chunk \(chunk): output is silent (energy=\(e))")
        }
    }
}
