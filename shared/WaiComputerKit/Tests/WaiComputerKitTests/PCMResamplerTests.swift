import XCTest
import AVFoundation
@testable import WaiComputerKit

final class PCMResamplerTests: XCTestCase {

    // MARK: - Init

    func testInitWithValidSourceFormat() {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 1,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source, targetSampleRate: 16_000)
        XCTAssertNotNil(resampler)
        XCTAssertEqual(resampler?.sourceFormat.sampleRate, 48_000)
    }

    func testInitDefaultsTo16kHzTarget() {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 44_100,
            channels: 1,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source)
        XCTAssertNotNil(resampler)
    }

    func testInitAcceptsStereoSource() {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 2,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source, targetSampleRate: 16_000)
        XCTAssertNotNil(resampler, "stereo → mono 16kHz conversion is supported by AVAudioConverter")
    }

    // MARK: - Convert

    func testConvertReturnsNilForEmptyBuffer() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 1,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source, targetSampleRate: 16_000)!

        let buffer = AVAudioPCMBuffer(pcmFormat: source, frameCapacity: 1024)!
        buffer.frameLength = 0
        XCTAssertNil(resampler.convert(buffer))
    }

    func testConvertDownsamples48kTo16k() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 1,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source, targetSampleRate: 16_000)!

        // 1 second of audio @ 48kHz mono
        let input = makeSineBuffer(format: source, frequency: 440, durationSeconds: 1)

        let output = try XCTUnwrap(resampler.convert(input))
        XCTAssertEqual(output.format.sampleRate, 16_000)
        XCTAssertEqual(output.format.channelCount, 1)

        // Output should have roughly 16000 frames (give some converter slack)
        let outFrames = Int(output.frameLength)
        XCTAssertGreaterThanOrEqual(outFrames, 15_900)
        XCTAssertLessThanOrEqual(outFrames, 16_100)
    }

    func testConvertDownsamples44_1kTo16k() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 44_100,
            channels: 1,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source, targetSampleRate: 16_000)!

        // 0.5 second of audio @ 44.1kHz mono
        let input = makeSineBuffer(format: source, frequency: 440, durationSeconds: 0.5)
        let output = try XCTUnwrap(resampler.convert(input))

        XCTAssertEqual(output.format.sampleRate, 16_000)
        let outFrames = Int(output.frameLength)
        // ~8000 frames expected (16000 * 0.5), allow generous tolerance
        XCTAssertGreaterThanOrEqual(outFrames, 7_900)
        XCTAssertLessThanOrEqual(outFrames, 8_100)
    }

    func testConvertProducesNonZeroSamplesForLoudInput() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 1,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source, targetSampleRate: 16_000)!

        // Loud sine wave
        let input = makeSineBuffer(format: source, frequency: 440, durationSeconds: 0.1, amplitude: 0.8)
        let output = try XCTUnwrap(resampler.convert(input))

        let outData = try XCTUnwrap(output.floatChannelData)
        var sumSq: Double = 0
        let n = Int(output.frameLength)
        for i in 0..<n {
            let s = Double(outData[0][i])
            sumSq += s * s
        }
        let rms = sqrt(sumSq / Double(n))
        XCTAssertGreaterThan(rms, 0.1, "loud 440Hz input should produce RMS > 0.1 after resampling")
    }

    func testConvertStereoToMono() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 2,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source, targetSampleRate: 16_000)!

        let input = makeSineBuffer(format: source, frequency: 440, durationSeconds: 0.1)
        let output = try XCTUnwrap(resampler.convert(input))

        XCTAssertEqual(output.format.channelCount, 1, "target is mono regardless of source channel count")
        XCTAssertEqual(output.format.sampleRate, 16_000)
    }

    // MARK: - Helpers

    /// Make a Float32 sine-wave buffer at the given format.
    private func makeSineBuffer(
        format: AVAudioFormat,
        frequency: Double,
        durationSeconds: Double,
        amplitude: Float = 0.5
    ) -> AVAudioPCMBuffer {
        let frames = AVAudioFrameCount(format.sampleRate * durationSeconds)
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames)!
        buffer.frameLength = frames

        guard let channelData = buffer.floatChannelData else {
            return buffer
        }

        let twoPi = 2.0 * Double.pi
        let increment = twoPi * frequency / format.sampleRate
        let chCount = Int(format.channelCount)

        for ch in 0..<chCount {
            var phase: Double = 0
            for i in 0..<Int(frames) {
                channelData[ch][i] = amplitude * Float(sin(phase))
                phase += increment
                if phase > twoPi { phase -= twoPi }
            }
        }

        return buffer
    }
}
