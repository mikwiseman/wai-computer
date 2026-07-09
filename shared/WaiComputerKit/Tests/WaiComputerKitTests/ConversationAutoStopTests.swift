import XCTest
import AVFoundation
@testable import WaiComputerKit

final class SpeechWindowClassificationTests: XCTestCase {

    private let config = ConversationAutoStopConfig.default

    /// A confident classifier verdict at conversational level is speech.
    func testConfidentSpeechWindowCounts() {
        XCTAssertTrue(config.isSpeech(SpeechWindowObservation(speechConfidence: 0.95, levelDb: -30)))
    }

    /// Music, typing, fans: the classifier keeps confidence far below the
    /// threshold no matter how loud they are — never speech.
    func testLoudNonSpeechIsRejected() {
        XCTAssertFalse(config.isSpeech(SpeechWindowObservation(speechConfidence: 0.03, levelDb: -12)))
    }

    /// Digital silence produces a flat low-confidence "speech" prior (~0.2
    /// observed on-device); it must stay below the threshold.
    func testDigitalSilencePriorIsRejected() {
        XCTAssertFalse(config.isSpeech(SpeechWindowObservation(speechConfidence: 0.21, levelDb: -95)))
    }

    /// A confident verdict on near-silent audio (residual TV bleed through a
    /// wall) is gated by the absolute level floor.
    func testConfidentButInaudibleWindowIsRejected() {
        XCTAssertFalse(config.isSpeech(SpeechWindowObservation(speechConfidence: 0.9, levelDb: -70)))
    }

    /// Quiet-but-audible distant speech (the RMS heuristic's blind spot) now
    /// counts: the classifier is confident and the level clears the gate.
    func testQuietDistantSpeechIsDetected() {
        XCTAssertTrue(config.isSpeech(SpeechWindowObservation(speechConfidence: 0.9, levelDb: -48)))
    }
}

final class AudioLevelMeterTests: XCTestCase {

    /// RMS of a PCM buffer: silent buffer → 0, half-scale square wave → 0.5,
    /// and a 2-channel buffer reports the louder channel.
    func testBufferRMSMeasuresLoudestChannel() throws {
        let format = try XCTUnwrap(AVAudioFormat(
            commonFormat: .pcmFormatFloat32, sampleRate: 16_000, channels: 2, interleaved: false
        ))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 1600))
        buffer.frameLength = 1600
        let channels = try XCTUnwrap(buffer.floatChannelData)
        for i in 0..<1600 {
            channels[0][i] = 0
            channels[1][i] = 0.5
        }
        let rms = AudioLevelMeter.peakChannelRMS(of: buffer)
        XCTAssertEqual(rms, 0.5, accuracy: 0.001)
    }
}

final class SoundAnalysisSpeechDetectorTests: XCTestCase {

    private func makeBuffer(
        channels: AVAudioChannelCount,
        frames: AVAudioFrameCount = 2560,
        fill: (Int, Int) -> Float
    ) throws -> AVAudioPCMBuffer {
        let format = try XCTUnwrap(AVAudioFormat(
            commonFormat: .pcmFormatFloat32, sampleRate: 16_000, channels: channels, interleaved: false
        ))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames))
        buffer.frameLength = frames
        let data = try XCTUnwrap(buffer.floatChannelData)
        for channel in 0..<Int(channels) {
            for frame in 0..<Int(frames) {
                data[channel][frame] = fill(channel, frame)
            }
        }
        return buffer
    }

    /// The system classifier only reads channel 0, so the detector must fold
    /// every channel into its mono feed: speech living only in channel 1
    /// (system audio of a call) must reach the analyzer.
    func testMixdownFoldsAllChannels() throws {
        let stereo = try makeBuffer(channels: 2) { channel, frame in
            channel == 1 ? sinf(Float(frame) * 0.2) * 0.5 : 0
        }
        let mono = try XCTUnwrap(SoundAnalysisSpeechDetector.monoMixdown(of: stereo))
        XCTAssertEqual(mono.format.channelCount, 1)
        XCTAssertEqual(mono.frameLength, stereo.frameLength)
        let rms = AudioLevelMeter.peakChannelRMS(of: mono)
        // Average of (0, 0.5·sine) — audible, half the single-channel RMS.
        XCTAssertGreaterThan(rms, 0.1)
    }

    /// Mono input passes through without copying.
    func testMonoPassesThrough() throws {
        let mono = try makeBuffer(channels: 1) { _, frame in sinf(Float(frame) * 0.2) * 0.3 }
        let out = try XCTUnwrap(SoundAnalysisSpeechDetector.monoMixdown(of: mono))
        XCTAssertTrue(out === mono)
    }

    /// End-to-end smoke test against the real system classifier: feeding
    /// buffers must produce windows, and non-speech audio (noise) must stay
    /// below the speech threshold. Speech-positive behavior is covered by
    /// live QA — test audio synthesis can't produce real voice here.
    func testDetectorEmitsLowConfidenceWindowsForNoise() throws {
        final class Box: @unchecked Sendable {
            let lock = NSLock()
            var observations: [SpeechWindowObservation] = []
            func append(_ o: SpeechWindowObservation) {
                lock.lock(); observations.append(o); lock.unlock()
            }
            var all: [SpeechWindowObservation] {
                lock.lock(); defer { lock.unlock() }; return observations
            }
        }
        let box = Box()
        let detector = try SoundAnalysisSpeechDetector { box.append($0) }

        // ~4 s of white noise in 160 ms buffers, like the capture cadence.
        var seed: UInt64 = 0x5DEECE66D
        for _ in 0..<25 {
            let buffer = try makeBuffer(channels: 1) { _, _ in
                seed = seed &* 6364136223846793005 &+ 1442695040888963407
                return (Float(seed >> 40) / Float(1 << 24) - 0.5) * 0.2
            }
            detector.process(buffer)
        }
        detector.finish()

        let observations = box.all
        XCTAssertGreaterThanOrEqual(observations.count, 3, "analyzer produced no windows")
        let config = ConversationAutoStopConfig.default
        XCTAssertTrue(
            observations.allSatisfy { !config.isSpeech($0) },
            "noise classified as speech: \(observations)"
        )
        // Level metering rode along with the windows.
        XCTAssertTrue(observations.allSatisfy { $0.levelDb > -40 && $0.levelDb < 0 })
    }
}

final class ConversationAutoStopMonitorTests: XCTestCase {

    private let start = Date(timeIntervalSince1970: 1_000_000)
    private var config: ConversationAutoStopConfig {
        ConversationAutoStopConfig(
            silenceTimeout: 240,
            callEndedTimeout: 30,
            countdown: 60
        )
    }

    private func makeMonitor() -> ConversationAutoStopMonitor {
        ConversationAutoStopMonitor(config: config, now: start)
    }

    /// Speech shorthand: a confident utterance spanning a few classifier
    /// windows (~0.5 s cadence) bumps voice activity.
    private func speak(_ monitor: ConversationAutoStopMonitor, at date: Date) {
        for i in 0..<3 {
            monitor.recordSpeechWindow(
                SpeechWindowObservation(speechConfidence: 0.95, levelDb: -28),
                at: date.addingTimeInterval(Double(i) * 0.5)
            )
        }
    }

    // MARK: - Silence path

    func testNoPromptBeforeSilenceTimeout() {
        let monitor = makeMonitor()
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(239)))
    }

    func testPromptFiresAfterSilenceTimeout() {
        let monitor = makeMonitor()
        let event = monitor.tick(at: start.addingTimeInterval(241))
        XCTAssertEqual(event, .beginPrompt(.silence))
        XCTAssertTrue(monitor.isPrompting)
    }

    func testVoiceActivityDefersPrompt() {
        let monitor = makeMonitor()
        speak(monitor, at: start.addingTimeInterval(200))
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(300)))
        let event = monitor.tick(at: start.addingTimeInterval(201 + 241))
        XCTAssertEqual(event, .beginPrompt(.silence))
    }

    /// A single confident window (stray shout, TV flicker) does not reset the
    /// silence clock; sustained speech does.
    func testSingleSpeechWindowDoesNotDeferPrompt() {
        let monitor = makeMonitor()
        monitor.recordSpeechWindow(
            SpeechWindowObservation(speechConfidence: 0.97, levelDb: -20),
            at: start.addingTimeInterval(200)
        )
        let event = monitor.tick(at: start.addingTimeInterval(241))
        XCTAssertEqual(event, .beginPrompt(.silence))
    }

    /// Loud non-speech windows (music, typing runs, fan spin-ups) never reset
    /// the silence clock, no matter how many arrive — the classifier keeps
    /// their confidence low. This was the RMS heuristic's core failure.
    func testLoudNonSpeechNeverResetsSilenceClock() {
        let monitor = makeMonitor()
        for second in stride(from: 0.0, through: 240.0, by: 0.5) {
            monitor.recordSpeechWindow(
                SpeechWindowObservation(speechConfidence: 0.05, levelDb: -15),
                at: start.addingTimeInterval(second)
            )
        }
        let event = monitor.tick(at: start.addingTimeInterval(241))
        XCTAssertEqual(event, .beginPrompt(.silence))
    }

    /// Isolated confident windows separated by quiet never accumulate into a
    /// sustained run.
    func testIsolatedSpeechWindowsDoNotAccumulate() {
        let monitor = makeMonitor()
        for burstStart in [60.0, 120.0, 180.0, 230.0] {
            monitor.recordSpeechWindow(
                SpeechWindowObservation(speechConfidence: 0.9, levelDb: -25),
                at: start.addingTimeInterval(burstStart)
            )
            monitor.recordSpeechWindow(
                SpeechWindowObservation(speechConfidence: 0.1, levelDb: -60),
                at: start.addingTimeInterval(burstStart + 0.5)
            )
        }
        let event = monitor.tick(at: start.addingTimeInterval(241))
        XCTAssertEqual(event, .beginPrompt(.silence))
    }

    // MARK: - Voice-activity surface (UI)

    func testVoiceActiveReflectsRecentSpeech() {
        let monitor = makeMonitor()
        speak(monitor, at: start.addingTimeInterval(100))
        XCTAssertTrue(monitor.isVoiceActive(at: start.addingTimeInterval(102)))
        XCTAssertFalse(monitor.isVoiceActive(at: start.addingTimeInterval(108)))
    }

    // MARK: - Prompt lifecycle

    func testSpeechDuringPromptCancelsIt() {
        let monitor = makeMonitor()
        _ = monitor.tick(at: start.addingTimeInterval(241))
        speak(monitor, at: start.addingTimeInterval(250))
        let event = monitor.tick(at: start.addingTimeInterval(252))
        XCTAssertEqual(event, .cancelPrompt)
        XCTAssertFalse(monitor.isPrompting)
        // Fully re-armed: next prompt needs another full silence window.
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(251 + 239)))
        XCTAssertEqual(monitor.tick(at: start.addingTimeInterval(251 + 242)), .beginPrompt(.silence))
    }

    func testCountdownExpiryAutoStopsOnce() {
        let monitor = makeMonitor()
        _ = monitor.tick(at: start.addingTimeInterval(241))
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(241 + 59)))
        let event = monitor.tick(at: start.addingTimeInterval(241 + 61))
        XCTAssertEqual(event, .autoStop(.silence))
        // Terminal: no further events even as time passes.
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(10_000)))
    }

    func testUserContinuedSnoozesPrompt() {
        let monitor = makeMonitor()
        _ = monitor.tick(at: start.addingTimeInterval(241))
        let resumeAt = start.addingTimeInterval(250)
        monitor.userContinued(at: resumeAt)
        XCTAssertFalse(monitor.isPrompting)
        XCTAssertNil(monitor.tick(at: resumeAt.addingTimeInterval(239)))
        XCTAssertEqual(monitor.tick(at: resumeAt.addingTimeInterval(241)), .beginPrompt(.silence))
    }

    func testPromptCountdownRemaining() {
        let monitor = makeMonitor()
        XCTAssertNil(monitor.promptCountdownRemaining(at: start))
        _ = monitor.tick(at: start.addingTimeInterval(241))
        let remaining = monitor.promptCountdownRemaining(at: start.addingTimeInterval(241 + 15))
        XCTAssertEqual(remaining ?? -1, 45, accuracy: 0.01)
    }

    // MARK: - Call-ended fast path

    func testCallEndedPromptsAfterShortQuietWindow() {
        let monitor = makeMonitor()
        speak(monitor, at: start.addingTimeInterval(100))
        monitor.noteCallEnded(at: start.addingTimeInterval(120))
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(120 + 29)))
        let event = monitor.tick(at: start.addingTimeInterval(120 + 31))
        XCTAssertEqual(event, .beginPrompt(.callEnded))
    }

    /// Speech after the call ends (conversation continues in the room) clears
    /// the fast path — only the regular silence timeout applies afterwards.
    func testSpeechAfterCallEndedClearsFastPath() {
        let monitor = makeMonitor()
        monitor.noteCallEnded(at: start.addingTimeInterval(100))
        speak(monitor, at: start.addingTimeInterval(110))
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(111 + 35)))
        let event = monitor.tick(at: start.addingTimeInterval(111 + 241))
        XCTAssertEqual(event, .beginPrompt(.silence))
    }

    /// A new call starting re-arms the fast path off.
    func testCallActiveClearsCallEnded() {
        let monitor = makeMonitor()
        monitor.noteCallEnded(at: start.addingTimeInterval(100))
        monitor.noteCallActive(at: start.addingTimeInterval(105))
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(105 + 35)))
    }

    /// Quiet time before the call ended counts only from the signal, not from
    /// the last speech (someone may have been on mute for a while).
    func testCallEndedQuietWindowCountsFromSignal() {
        let monitor = makeMonitor()
        speak(monitor, at: start.addingTimeInterval(10))
        monitor.noteCallEnded(at: start.addingTimeInterval(200))
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(200 + 29)))
        XCTAssertEqual(
            monitor.tick(at: start.addingTimeInterval(200 + 31)),
            .beginPrompt(.callEnded)
        )
    }

    // MARK: - Pause interaction

    func testPausedRecordingNeverPrompts() {
        let monitor = makeMonitor()
        monitor.setPaused(true, at: start.addingTimeInterval(10))
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(10_000)))
    }

    func testResumeReArmsFromResumeTime() {
        let monitor = makeMonitor()
        monitor.setPaused(true, at: start.addingTimeInterval(10))
        let resumeAt = start.addingTimeInterval(7_200) // resumed 2h later
        monitor.setPaused(false, at: resumeAt)
        XCTAssertNil(monitor.tick(at: resumeAt.addingTimeInterval(239)))
        XCTAssertEqual(monitor.tick(at: resumeAt.addingTimeInterval(241)), .beginPrompt(.silence))
    }

    /// Speech windows that race in while paused must not bump the silence clock.
    func testAudioWhilePausedIsIgnored() {
        let monitor = makeMonitor()
        monitor.setPaused(true, at: start.addingTimeInterval(10))
        speak(monitor, at: start.addingTimeInterval(20))
        monitor.setPaused(false, at: start.addingTimeInterval(30))
        // Silence clock restarts at resume (30), not at the paused speech (20).
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(30 + 239)))
        XCTAssertEqual(monitor.tick(at: start.addingTimeInterval(30 + 241)), .beginPrompt(.silence))
    }

    /// Pausing mid-prompt dismisses the prompt without firing the auto action.
    func testPauseDuringPromptCancelsIt() {
        let monitor = makeMonitor()
        _ = monitor.tick(at: start.addingTimeInterval(241))
        monitor.setPaused(true, at: start.addingTimeInterval(250))
        XCTAssertFalse(monitor.isPrompting)
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(241 + 120)))
    }
}
