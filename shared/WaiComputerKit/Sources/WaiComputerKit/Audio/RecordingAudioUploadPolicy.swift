import Foundation

public enum RecordingAudioUploadPolicy {
    /// ElevenLabs file STT accepts uploaded files from 100 ms upward.
    /// Keep this as the transport minimum; product-level "too quiet" or
    /// "too short to be useful" decisions should use a separate threshold.
    public static let minimumDurationSeconds: TimeInterval = 0.1

    public static func canUploadFinalizedAudio(
        durationSeconds: TimeInterval?,
        pcmBytesWritten: Int64
    ) -> Bool {
        guard let durationSeconds else { return false }
        return pcmBytesWritten > 0 && durationSeconds >= minimumDurationSeconds
    }
}
