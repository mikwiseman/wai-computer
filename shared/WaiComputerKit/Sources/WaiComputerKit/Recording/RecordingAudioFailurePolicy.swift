import Foundation

public enum RecordingAudioFailurePolicy {
    public static let retryableServerFailureCodes: Set<String> = [
        "processing_enqueue_failed",
        "processing_failed",
        "processing_interrupted",
        "processing_retry_exhausted",
        "processing_timeout",
        "provider_unavailable",
        "staged_file_missing",
        "staging_failed",
        "transcription_halted",
        "upload_abandoned",
        "upload_size_mismatch",
        "audio_decode_failed",
        // Temporary daily transcription caps (reset at midnight UTC). Marking
        // them permanent used to delete the only recoverable copy of a
        // recording that merely arrived on a busy day.
        "user_minutes",
        "global_minutes",
    ]

    public static func isRetryableServerFailureCode(_ code: String?) -> Bool {
        guard let normalizedCode = code?.trimmingCharacters(in: .whitespacesAndNewlines),
              !normalizedCode.isEmpty else {
            return false
        }
        return retryableServerFailureCodes.contains(normalizedCode)
    }
}
