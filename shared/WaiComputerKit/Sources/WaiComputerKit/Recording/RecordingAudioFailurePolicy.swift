import Foundation

public enum RecordingAudioFailurePolicy {
    public static let retryableServerFailureCodes: Set<String> = [
        "processing_enqueue_failed",
        "processing_failed",
        "processing_retry_exhausted",
        "processing_timeout",
        "provider_unavailable",
        "staged_file_missing",
        "staging_failed",
        "transcription_halted",
        "upload_size_mismatch",
    ]

    public static func isRetryableServerFailureCode(_ code: String?) -> Bool {
        guard let normalizedCode = code?.trimmingCharacters(in: .whitespacesAndNewlines),
              !normalizedCode.isEmpty else {
            return false
        }
        return retryableServerFailureCodes.contains(normalizedCode)
    }
}
