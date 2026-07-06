import XCTest
import AVFoundation
@testable import WaiComputerKit

final class SpeechActivityEstimatorTests: XCTestCase {

    // MARK: - Basic detection

    /// A dead-quiet room produces no speech activity, ever.
    func testSilenceIsNeverSpeech() {
        var estimator = SpeechActivityEstimator()
        for _ in 0..<200 {
            XCTAssertFalse(estimator.isSpeech(rms: 0.000_01))
        }
    }

    /// Loud speech over a quiet floor is detected once the floor is warmed up.
    func testSpeechOverQuietFloorIsDetected() {
        var estimator = SpeechActivityEstimator()
        for _ in 0..<50 {
            _ = estimator.isSpeech(rms: 0.000_1) // ~-80 dBFS room tone
        }
        XCTAssertTrue(estimator.isSpeech(rms: 0.05)) // ~-26 dBFS speech
    }

    /// Steady background noise (fan/AC) raises the floor so the noise itself
    /// never counts as speech.
    func testSteadyBackgroundNoiseIsNotSpeech() {
        var estimator = SpeechActivityEstimator()
        var detections = 0
        for _ in 0..<400 {
            if estimator.isSpeech(rms: 0.004) { detections += 1 } // ~-48 dBFS hum
        }
        // The first buffers may fire before the floor adapts; after warm-up the
        // constant hum must be classified as floor, not speech.
        var lateDetections = 0
        for _ in 0..<200 {
            if estimator.isSpeech(rms: 0.004) { lateDetections += 1 }
        }
        XCTAssertEqual(lateDetections, 0)
        _ = detections
    }

    /// Speech clearly above a noisy floor is still detected.
    func testSpeechOverNoisyFloorIsDetected() {
        var estimator = SpeechActivityEstimator()
        for _ in 0..<300 {
            _ = estimator.isSpeech(rms: 0.004) // warm the floor at ~-48 dBFS
        }
        XCTAssertTrue(estimator.isSpeech(rms: 0.1)) // ~-20 dBFS speech
    }

    /// Ultra-quiet blips above a near-zero floor stay below the absolute gate.
    func testAbsoluteMinimumGateBlocksUltraQuietBlips() {
        var estimator = SpeechActivityEstimator()
        for _ in 0..<100 {
            _ = estimator.isSpeech(rms: 0.000_001) // digital-silence floor
        }
        // 12 dB over that floor but far below any real speech level.
        XCTAssertFalse(estimator.isSpeech(rms: 0.000_004))
    }


    /// A conversation with natural pauses keeps the floor at the pause level,
    /// so speech keeps being detected even after minutes of talking.
    func testConversationWithPausesKeepsDetectingSpeech() {
        var estimator = SpeechActivityEstimator()
        var lastRoundDetected = false
        for _ in 0..<40 { // ~40 speech/pause cycles
            for _ in 0..<12 { lastRoundDetected = estimator.isSpeech(rms: 0.05) }
            for _ in 0..<6 { _ = estimator.isSpeech(rms: 0.000_2) } // breath pause
        }
        XCTAssertTrue(lastRoundDetected)
    }

    /// Quiet speech (~-45 dBFS) in a quiet room clears the adaptive floor.
    func testQuietSpeechInQuietRoomIsDetected() {
        var estimator = SpeechActivityEstimator()
        for _ in 0..<100 {
            _ = estimator.isSpeech(rms: 0.000_3) // ~-70 dBFS room tone
        }
        XCTAssertTrue(estimator.isSpeech(rms: 0.005_6)) // ~-45 dBFS distant speech
    }

    /// The same ~-45 dBFS level over a ~-48 dBFS fan floor is floor jitter,
    /// not speech.
    func testNearFloorLevelOverNoisyFloorIsRejected() {
        var estimator = SpeechActivityEstimator()
        for _ in 0..<300 {
            _ = estimator.isSpeech(rms: 0.004) // ~-48 dBFS fan
        }
        XCTAssertFalse(estimator.isSpeech(rms: 0.005_6)) // ~-45 dBFS
    }

    /// Continuous loud audio (webinar with no pauses) saturates the sliding
    /// window, but the speech ceiling keeps every frame classified as speech —
    /// the estimator must never talk itself out of detecting an ongoing talk.
    func testContinuousLoudSpeechNeverStopsBeingSpeech() {
        var estimator = SpeechActivityEstimator()
        var allDetected = true
        for _ in 0..<600 { // ~96 s of nonstop -26 dBFS audio
            if !estimator.isSpeech(rms: 0.05) { allDetected = false }
        }
        XCTAssertTrue(allDetected)
    }

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
        let rms = SpeechActivityEstimator.peakChannelRMS(of: buffer)
        XCTAssertEqual(rms, 0.5, accuracy: 0.001)
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

    /// Speech shorthand: sustained speech-level audio (~1 s) bumps voice
    /// activity; short bursts are ignored by design.
    private func speak(_ monitor: ConversationAutoStopMonitor, at date: Date) {
        for i in 0..<6 {
            monitor.recordAudioLevel(rms: 0.08, at: date.addingTimeInterval(Double(i) * 0.16))
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
        let event = monitor.tick(at: start.addingTimeInterval(200 + 241))
        XCTAssertEqual(event, .beginPrompt(.silence))
    }

    /// A single lone frame above the speech threshold (door slam) does not
    /// reset the silence clock; only sustained speech does.
    func testSingleFramePopDoesNotDeferPrompt() {
        let monitor = makeMonitor()
        monitor.recordAudioLevel(rms: 0.5, at: start.addingTimeInterval(200))
        let event = monitor.tick(at: start.addingTimeInterval(241))
        XCTAssertEqual(event, .beginPrompt(.silence))
    }

    /// Repeated short bursts (chair creaks, keyboard runs — under the
    /// sustained-speech length) never reset the silence clock, no matter how
    /// often they happen. This is the real quiet-room failure mode observed
    /// live: sporadic ~0.3 s creaks kept a hard-reset clock at zero forever.
    func testShortBurstsDoNotResetSilenceClock() {
        let monitor = makeMonitor()
        for burstStart in [60.0, 120.0, 180.0, 230.0] {
            for i in 0..<3 { // 3 frames < sustainedSpeechFrames (4)
                monitor.recordAudioLevel(
                    rms: 0.1,
                    at: start.addingTimeInterval(burstStart + Double(i) * 0.16)
                )
            }
            // Quiet frame ends each burst.
            monitor.recordAudioLevel(rms: 0.000_1, at: start.addingTimeInterval(burstStart + 0.5))
        }
        let event = monitor.tick(at: start.addingTimeInterval(241))
        XCTAssertEqual(event, .beginPrompt(.silence))
    }

    // MARK: - Prompt lifecycle

    func testSpeechDuringPromptCancelsIt() {
        let monitor = makeMonitor()
        _ = monitor.tick(at: start.addingTimeInterval(241))
        speak(monitor, at: start.addingTimeInterval(250))
        let event = monitor.tick(at: start.addingTimeInterval(251))
        XCTAssertEqual(event, .cancelPrompt)
        XCTAssertFalse(monitor.isPrompting)
        // Fully re-armed: next prompt needs another full silence window.
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(250 + 239)))
        XCTAssertEqual(monitor.tick(at: start.addingTimeInterval(250 + 242)), .beginPrompt(.silence))
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
        XCTAssertNil(monitor.tick(at: start.addingTimeInterval(110 + 35)))
        let event = monitor.tick(at: start.addingTimeInterval(110 + 241))
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

    /// Audio frames that race in while paused must not bump the silence clock.
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
