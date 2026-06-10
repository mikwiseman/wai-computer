import XCTest
@testable import WaiComputerKit

final class WaiComputerKitTests: XCTestCase {

    func testRecordingTypeEncoding() throws {
        let recording = Recording(
            id: "test-id",
            title: "Test Recording",
            type: .meeting,
            createdAt: Date()
        )

        let encoder = JSONEncoder()
        let data = try encoder.encode(recording)
        let json = String(data: data, encoding: .utf8)!

        XCTAssertTrue(json.contains("\"type\":\"meeting\""))
    }

    func testSegmentFormattedTimestamp() {
        let segment = Segment(
            id: "seg-1",
            content: "Test content",
            startMs: 65000  // 1:05
        )

        XCTAssertEqual(segment.formattedTimestamp, "01:05")
    }

    func testSegmentDuration() {
        let segment = Segment(
            id: "seg-1",
            content: "Test content",
            startMs: 1000,
            endMs: 5000
        )

        XCTAssertEqual(segment.durationMs, 4000)
    }

    func testActionItemStatusValues() {
        XCTAssertEqual(ActionItem.Status.pending.rawValue, "pending")
        XCTAssertEqual(ActionItem.Status.inProgress.rawValue, "in_progress")
        XCTAssertEqual(ActionItem.Status.completed.rawValue, "completed")
    }

    func testAudioCaptureConfig() {
        let config = AudioCaptureConfig.default

        XCTAssertEqual(config.sampleRate, 16000)
        XCTAssertEqual(config.channelCount, 1)
        XCTAssertEqual(config.bufferSize, 2560)
        XCTAssertNotNil(config.format)
    }
}
