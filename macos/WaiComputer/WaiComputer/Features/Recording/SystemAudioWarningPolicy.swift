enum SystemAudioWarningPolicy {
    /// The capture layer owns detection. Absence of audible system samples is not
    /// enough for UI: a newly-started call can be silent while the tap is healthy.
    static func shouldShowCaptureWarning(
        systemAudioStalled: Bool,
        systemAudioReceivedAny: Bool
    ) -> Bool {
        _ = systemAudioReceivedAny
        return systemAudioStalled
    }
}
