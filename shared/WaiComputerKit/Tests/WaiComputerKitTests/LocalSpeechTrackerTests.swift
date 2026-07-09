import XCTest
@testable import WaiComputerKit

final class LocalSpeechTrackerTests: XCTestCase {
    private let sampleRate = 16_000.0

    private func window(amplitude: Float, ms: Int) -> [Float] {
        let frames = Int(sampleRate * Double(ms) / 1000.0)
        // Constant-amplitude block: RMS == amplitude.
        return [Float](repeating: amplitude, count: frames)
    }

    func testDetectsLocalSpeechAgainstQuietSystem() {
        var tracker = LocalSpeechTracker(sampleRate: sampleRate)
        // 480ms of loud mic over quiet system, then 800ms silence.
        for _ in 0..<3 {
            tracker.ingest(mic: window(amplitude: 0.1, ms: 160), system: window(amplitude: 0.001, ms: 160))
        }
        for _ in 0..<5 {
            tracker.ingest(mic: window(amplitude: 0.0, ms: 160), system: window(amplitude: 0.001, ms: 160))
        }
        let intervals = tracker.finish()
        XCTAssertEqual(intervals.count, 1)
        XCTAssertEqual(intervals[0][0], 0)
        XCTAssertEqual(intervals[0][1], 480)
    }

    func testEchoLeakDoesNotCountAsLocalSpeech() {
        var tracker = LocalSpeechTracker(sampleRate: sampleRate)
        // System audio loud; mic picks up leak at comparable level -> not local.
        for _ in 0..<6 {
            tracker.ingest(mic: window(amplitude: 0.05, ms: 160), system: window(amplitude: 0.08, ms: 160))
        }
        XCTAssertTrue(tracker.finish().isEmpty)
    }

    func testShortBlipIsDropped() {
        var tracker = LocalSpeechTracker(sampleRate: sampleRate)
        tracker.ingest(mic: window(amplitude: 0.1, ms: 160), system: [])
        for _ in 0..<6 {
            tracker.ingest(mic: window(amplitude: 0.0, ms: 160), system: [])
        }
        XCTAssertTrue(tracker.finish().isEmpty, "160ms blip must not become an interval")
    }

    func testBreathPausesMergeIntoOneInterval() {
        var tracker = LocalSpeechTracker(sampleRate: sampleRate)
        // speech 480ms, pause 320ms (< merge gap 600), speech 480ms
        for _ in 0..<3 { tracker.ingest(mic: window(amplitude: 0.1, ms: 160), system: []) }
        for _ in 0..<2 { tracker.ingest(mic: window(amplitude: 0.0, ms: 160), system: []) }
        for _ in 0..<3 { tracker.ingest(mic: window(amplitude: 0.1, ms: 160), system: []) }
        let intervals = tracker.finish()
        XCTAssertEqual(intervals.count, 1)
        XCTAssertEqual(intervals[0][0], 0)
        XCTAssertEqual(intervals[0][1], 1280)
    }

    func testLongSilenceSplitsIntervals() {
        var tracker = LocalSpeechTracker(sampleRate: sampleRate)
        for _ in 0..<3 { tracker.ingest(mic: window(amplitude: 0.1, ms: 160), system: []) }
        for _ in 0..<6 { tracker.ingest(mic: window(amplitude: 0.0, ms: 160), system: []) }
        for _ in 0..<3 { tracker.ingest(mic: window(amplitude: 0.1, ms: 160), system: []) }
        let intervals = tracker.finish()
        XCTAssertEqual(intervals.count, 2)
        XCTAssertEqual(intervals[0], [0, 480])
        XCTAssertEqual(intervals[1], [1440, 1920])
    }

    func testFrameClockIgnoresWallTime() {
        var tracker = LocalSpeechTracker(sampleRate: sampleRate)
        tracker.ingest(mic: window(amplitude: 0.1, ms: 500), system: [])
        // Nothing ingested "for a long wall-clock time" — clock must not move.
        tracker.ingest(mic: window(amplitude: 0.1, ms: 500), system: [])
        let intervals = tracker.finish()
        XCTAssertEqual(intervals, [[0, 1000]])
    }

    func testSidecarJSONShape() throws {
        let json = try XCTUnwrap(
            CaptureSidecar.json(capture: "dual_mono_mix", localSpeechIntervalsMs: [[0, 1200], [3000, 4000]])
        )
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any]
        )
        XCTAssertEqual(object["version"] as? Int, 1)
        XCTAssertEqual(object["capture"] as? String, "dual_mono_mix")
        XCTAssertEqual(object["aec"] as? Bool, false)
        XCTAssertEqual(object["local_speech_ms"] as? [[Int]], [[0, 1200], [3000, 4000]])
    }

    func testManifestRoundtripsCaptureMetadata() throws {
        let sidecar = try XCTUnwrap(
            CaptureSidecar.json(capture: "dual_mono_mix", localSpeechIntervalsMs: [[0, 900]])
        )
        var manifest = RecordingBackupManifest(
            recordingId: "rec-1",
            title: nil,
            recordingType: "meeting",
            createdAt: Date(),
            durationSeconds: 10,
            segmentCount: 0,
            transcript: nil,
            lastErrorMessage: nil,
            updatedAt: Date()
        )
        manifest.captureMetadataJSON = sidecar

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(
            RecordingBackupManifest.self,
            from: encoder.encode(manifest)
        )
        XCTAssertEqual(decoded.captureMetadataJSON, sidecar)
    }
}
