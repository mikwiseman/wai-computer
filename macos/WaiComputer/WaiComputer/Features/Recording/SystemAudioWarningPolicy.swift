import Foundation

enum SystemAudioWarningPolicy {
    enum HeaderIndicator: Equatable {
        case micAndSystem
        case systemAudioStarting
        case systemAudioDegraded
        case microphoneOnly
    }

    /// The capture layer owns detection. Absence of audible system samples is not
    /// enough for UI: a newly-started call can be silent while the tap is healthy.
    static func shouldShowCaptureWarning(
        systemAudioStalled: Bool,
        systemAudioReceivedAny: Bool
    ) -> Bool {
        _ = systemAudioReceivedAny
        return systemAudioStalled
    }

    static func headerIndicator(
        requestedSystemAudio: Bool,
        hasSystemAudio: Bool,
        warning: String?
    ) -> HeaderIndicator {
        guard requestedSystemAudio else {
            return .microphoneOnly
        }
        if warning != nil {
            return .systemAudioDegraded
        }
        if hasSystemAudio {
            return .micAndSystem
        }
        return .systemAudioStarting
    }
}

enum SystemAudioReadinessPolicy {
    enum Status: Equatable {
        case unsupported
        case setupNeeded
        case restartRequired
        case ready
    }

    static func status(
        isSupported: Bool,
        preflightPassedInCurrentProcess: Bool,
        openedSettingsDuringCurrentAttempt: Bool
    ) -> Status {
        guard isSupported else {
            return .unsupported
        }
        if preflightPassedInCurrentProcess {
            return .ready
        }
        if openedSettingsDuringCurrentAttempt {
            return .restartRequired
        }
        return .setupNeeded
    }
}

enum OnboardingDictationSandboxPolicy {
    static func textAfterFinalTranscript(
        currentText: String,
        textBeforeUtterance: String?,
        finalTranscript: String
    ) -> String {
        let transcript = finalTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else {
            return currentText
        }
        if textInserterAlreadyUpdatedSandbox(
            currentText: currentText,
            textBeforeUtterance: textBeforeUtterance,
            finalTranscript: transcript
        ) {
            return currentText
        }
        return append(transcript, to: currentText)
    }

    private static func textInserterAlreadyUpdatedSandbox(
        currentText: String,
        textBeforeUtterance: String?,
        finalTranscript: String
    ) -> Bool {
        let current = normalized(currentText)
        let before = textBeforeUtterance.map(normalized)
        let transcript = normalized(finalTranscript)

        guard !current.isEmpty, !transcript.isEmpty else {
            return false
        }

        if let before, current == before {
            return false
        }

        return current.hasSuffix(transcript)
    }

    private static func append(_ transcript: String, to currentText: String) -> String {
        guard !currentText.isEmpty else {
            return transcript
        }
        let needsSpace = !(currentText.last?.isWhitespace ?? true)
        return currentText + (needsSpace ? " " : "") + transcript
    }

    private static func normalized(_ text: String) -> String {
        text
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .components(separatedBy: .whitespacesAndNewlines)
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }
}
