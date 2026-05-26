import XCTest
@testable import WaiComputerKit

final class RecordingAudioUploadPolicyTests: XCTestCase {
    func testRejectsMissingDuration() {
        XCTAssertFalse(
            RecordingAudioUploadPolicy.canUploadFinalizedAudio(
                durationSeconds: nil,
                pcmBytesWritten: 3_200
            )
        )
    }

    func testRejectsEmptyAudio() {
        XCTAssertFalse(
            RecordingAudioUploadPolicy.canUploadFinalizedAudio(
                durationSeconds: 1,
                pcmBytesWritten: 0
            )
        )
    }

    func testRejectsAudioBelowProviderMinimum() {
        XCTAssertFalse(
            RecordingAudioUploadPolicy.canUploadFinalizedAudio(
                durationSeconds: 0.08,
                pcmBytesWritten: 2_560
            )
        )
    }

    func testAcceptsAudioAtProviderMinimum() {
        XCTAssertTrue(
            RecordingAudioUploadPolicy.canUploadFinalizedAudio(
                durationSeconds: 0.1,
                pcmBytesWritten: 3_200
            )
        )
    }
}
