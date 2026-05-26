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

    func testConvertProcessesContinuousCaptureBuffers() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 1,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source, targetSampleRate: 16_000)!
        let input = makeSineBuffer(format: source, frequency: 440, durationSeconds: 0.16)

        var frameCounts: [Int] = []
        for _ in 0..<8 {
            let output = try XCTUnwrap(resampler.convert(input))
            frameCounts.append(Int(output.frameLength))
        }

        XCTAssertEqual(frameCounts.count, 8)
        for frameCount in frameCounts {
            XCTAssertGreaterThanOrEqual(frameCount, 2_500)
            XCTAssertLessThanOrEqual(frameCount, 2_700)
        }
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

    func testConvertHonors24kTargetSampleRate() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 1,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source, targetSampleRate: 24_000)!

        let input = makeSineBuffer(format: source, frequency: 440, durationSeconds: 0.2)
        let output = try XCTUnwrap(resampler.convert(input))

        XCTAssertEqual(output.format.sampleRate, 24_000)
        XCTAssertEqual(output.format.channelCount, 1)
        XCTAssertGreaterThanOrEqual(Int(output.frameLength), 4_700)
        XCTAssertLessThanOrEqual(Int(output.frameLength), 4_900)
    }

    func testConvertAppliesAntiAliasingForAboveNyquistTone() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 1,
            interleaved: false
        )!
        let resampler = PCMResampler(source: source, targetSampleRate: 16_000)!

        let input = makeSineBuffer(format: source, frequency: 12_000, durationSeconds: 0.4, amplitude: 0.9)
        let output = try XCTUnwrap(resampler.convert(input))

        XCTAssertLessThan(
            try rms(output),
            0.02,
            "12kHz input must be filtered before 16kHz output instead of aliasing into the speech band"
        )
    }

    // MARK: - CaptureAudioProcessor

    func testCaptureAudioProcessorResamples48kStereoTo16kMono() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 2,
            interleaved: false
        )!
        let processor = try XCTUnwrap(CaptureAudioProcessor(config: .default))
        let input = makeSineBuffer(format: source, frequency: 440, durationSeconds: 0.1)

        let output = try XCTUnwrap(processor.process(input))

        XCTAssertEqual(output.format.sampleRate, 16_000)
        XCTAssertEqual(output.format.channelCount, 1)
        XCTAssertGreaterThanOrEqual(Int(output.frameLength), 1_500)
        XCTAssertLessThanOrEqual(Int(output.frameLength), 1_700)
        XCTAssertEqual(processor.snapshot.buffersReceived, 1)
        XCTAssertEqual(processor.snapshot.buffersYielded, 1)
        XCTAssertEqual(processor.snapshot.resamplerRebuilds, 1)
    }

    func testCaptureAudioProcessorResamplesContinuousBuffers() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 2,
            interleaved: false
        )!
        let processor = try XCTUnwrap(CaptureAudioProcessor(config: .default))
        let input = makeSineBuffer(format: source, frequency: 440, durationSeconds: 0.16)

        var outputs: [AVAudioPCMBuffer] = []
        for _ in 0..<8 {
            outputs.append(try XCTUnwrap(processor.process(input)))
        }

        XCTAssertEqual(processor.snapshot.buffersReceived, 8)
        XCTAssertEqual(processor.snapshot.buffersYielded, 8)
        XCTAssertEqual(processor.snapshot.conversionFailures, 0)
        XCTAssertEqual(processor.snapshot.resamplerRebuilds, 1)
        for output in outputs {
            XCTAssertEqual(output.format.sampleRate, 16_000)
            XCTAssertEqual(output.format.channelCount, 1)
            XCTAssertGreaterThanOrEqual(Int(output.frameLength), 2_500)
            XCTAssertLessThanOrEqual(Int(output.frameLength), 2_700)
        }
    }

    func testCaptureAudioProcessorUsesConfigured24kTarget() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 1,
            interleaved: false
        )!
        let config = AudioCaptureConfig(sampleRate: 24_000, channelCount: 1, bufferSize: 2_400)
        let processor = try XCTUnwrap(CaptureAudioProcessor(config: config))
        let input = makeSineBuffer(format: source, frequency: 440, durationSeconds: 0.1)

        let output = try XCTUnwrap(processor.process(input))

        XCTAssertEqual(output.format.sampleRate, 24_000)
        XCTAssertEqual(output.format.channelCount, 1)
        XCTAssertGreaterThanOrEqual(Int(output.frameLength), 2_300)
        XCTAssertLessThanOrEqual(Int(output.frameLength), 2_500)
    }

    func testCaptureAudioProcessorCopiesMatchingBuffersBeforeYielding() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 16_000,
            channels: 1,
            interleaved: false
        )!
        let processor = try XCTUnwrap(CaptureAudioProcessor(config: .default))
        let input = makeSineBuffer(format: source, frequency: 440, durationSeconds: 0.1)

        let output = try XCTUnwrap(processor.process(input))

        XCTAssertFalse(output === input)
        XCTAssertEqual(output.format.sampleRate, input.format.sampleRate)
        XCTAssertEqual(output.frameLength, input.frameLength)
        XCTAssertEqual(processor.snapshot.passthroughCopies, 1)
    }

    func testCaptureAudioProcessorCountsEmptyBuffers() throws {
        let source = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 16_000,
            channels: 1,
            interleaved: false
        )!
        let processor = try XCTUnwrap(CaptureAudioProcessor(config: .default))
        let input = AVAudioPCMBuffer(pcmFormat: source, frameCapacity: 128)!
        input.frameLength = 0

        XCTAssertNil(processor.process(input))
        XCTAssertEqual(processor.snapshot.emptyBuffers, 1)
        XCTAssertTrue(processor.snapshot.hasFailures)
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

    private func rms(_ buffer: AVAudioPCMBuffer) throws -> Double {
        let data = try XCTUnwrap(buffer.floatChannelData)
        let frames = Int(buffer.frameLength)
        guard frames > 0 else { return 0 }
        var sumSq: Double = 0
        for i in 0..<frames {
            let sample = Double(data[0][i])
            sumSq += sample * sample
        }
        return sqrt(sumSq / Double(frames))
    }
}
