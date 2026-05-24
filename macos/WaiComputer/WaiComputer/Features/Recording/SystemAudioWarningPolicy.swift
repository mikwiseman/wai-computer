import Foundation
import WaiComputerKit

enum RecordingCopy {
    static func importPanelTitle(language: LanguageManager.SupportedLanguage) -> String {
        text("Import Audio File", "Импорт аудиофайла", language: language)
    }

    static func importProcessingFailedFallback(language: LanguageManager.SupportedLanguage) -> String {
        text(
            "We couldn't transcribe that audio file right now. Please try again in a moment.",
            "Не удалось расшифровать этот аудиофайл сейчас. Попробуй еще раз через минуту.",
            language: language
        )
    }

    static func systemAudioCaptureUnavailableMessage(language: LanguageManager.SupportedLanguage) -> String {
        text(
            "System audio capture couldn't start. Check Audio Capture permission in System Settings and try again.",
            "Не удалось запустить захват звука Mac. Проверь разрешение записи аудио в Системных настройках и попробуй снова.",
            language: language
        )
    }

    private static func text(
        _ english: String,
        _ russian: String,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        switch language {
        case .russian:
            return russian
        case .english:
            return english
        case .followSystem:
            let preferred = Locale.preferredLanguages.first?.lowercased() ?? ""
            return preferred.hasPrefix("ru") ? russian : english
        }
    }
}

enum OnboardingPermissionPrimaryActionPolicy {
    enum MicrophoneStatus: Equatable {
        case granted
        case requestable
        case settingsRequired
    }

    enum AccessibilityStatus: Equatable {
        case granted
        case denied
        case staleNeedsRestart
    }

    static func primaryButtonTitle(
        microphoneStatus: MicrophoneStatus,
        accessibilityStatus: AccessibilityStatus,
        systemAudioReadiness: SystemAudioReadinessPolicy.Status,
        restartRecommended: Bool,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        if permissionsReady(
            microphoneStatus: microphoneStatus,
            accessibilityStatus: accessibilityStatus,
            systemAudioReadiness: systemAudioReadiness
        ) {
            return text("Continue", "Продолжить", language: language)
        }
        if restartRecommended {
            return text("Restart WaiComputer", "Перезапустить WaiComputer", language: language)
        }
        switch microphoneStatus {
        case .requestable:
            return text("Grant Microphone", "Разрешить микрофон", language: language)
        case .settingsRequired:
            return text("Open Microphone Settings", "Открыть настройки микрофона", language: language)
        case .granted:
            break
        }
        if accessibilityStatus == .denied {
            return text("Open Accessibility Settings", "Открыть Универсальный доступ", language: language)
        }
        if systemAudioReadiness == .setupNeeded {
            return text("Set Up System Audio", "Настроить звук Mac", language: language)
        }
        return text("Open Settings", "Открыть настройки", language: language)
    }

    static func microphoneRowActionLabel(
        microphoneStatus: MicrophoneStatus,
        language: LanguageManager.SupportedLanguage
    ) -> String? {
        switch microphoneStatus {
        case .granted:
            return nil
        case .requestable:
            return text("Grant", "Разрешить", language: language)
        case .settingsRequired:
            return text("Open Settings", "Открыть настройки", language: language)
        }
    }

    private static func permissionsReady(
        microphoneStatus: MicrophoneStatus,
        accessibilityStatus: AccessibilityStatus,
        systemAudioReadiness: SystemAudioReadinessPolicy.Status
    ) -> Bool {
        microphoneStatus == .granted
            && accessibilityStatus == .granted
    }

    private static func text(
        _ english: String,
        _ russian: String,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        switch language {
        case .russian:
            return russian
        case .english:
            return english
        case .followSystem:
            let preferred = Locale.preferredLanguages.first?.lowercased() ?? ""
            return preferred.hasPrefix("ru") ? russian : english
        }
    }
}

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

    static func permissionStatus(for readiness: Status) -> MacInputPermission.Status {
        switch readiness {
        case .ready:
            return .granted
        case .restartRequired:
            return .staleNeedsRestart
        case .setupNeeded, .unsupported:
            return .denied
        }
    }

    static func readiness(from permissionStatus: MacInputPermission.Status) -> Status {
        switch permissionStatus {
        case .granted:
            return .ready
        case .denied:
            return .setupNeeded
        case .staleNeedsRestart:
            return .restartRequired
        }
    }
}

enum SystemAudioPermissionPreflight {
    static let defaultTimeout: TimeInterval = 3.0

    static func receivedBuffers(timeout: TimeInterval = defaultTimeout) async throws -> Bool {
        guard #available(macOS 14.2, *) else {
            return false
        }

        let capture = SystemAudioCapture()
        do {
            try await capture.startRecording()
            let receivedBuffers = await capture.waitForAudioBuffers(timeout: timeout)
            await capture.stopRecording()
            return receivedBuffers
        } catch {
            await capture.stopRecording()
            throw error
        }
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
