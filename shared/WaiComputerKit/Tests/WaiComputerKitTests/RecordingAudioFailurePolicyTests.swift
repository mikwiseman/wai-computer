import XCTest
@testable import WaiComputerKit

final class RecordingAudioFailurePolicyTests: XCTestCase {
    func testOnlyServerApprovedAudioFailureCodesRetry() {
        for code in [
            "processing_enqueue_failed",
            "processing_failed",
            "processing_retry_exhausted",
            "processing_timeout",
            "provider_unavailable",
            "staged_file_missing",
            "staging_failed",
            "transcription_halted",
            "upload_size_mismatch",
        ] {
            XCTAssertTrue(RecordingAudioFailurePolicy.isRetryableServerFailureCode(code))
        }

        for code in [nil, "", " ", "audio_decode_failed", "transcript_empty", "file_too_large"] {
            XCTAssertFalse(RecordingAudioFailurePolicy.isRetryableServerFailureCode(code))
        }
    }
}
