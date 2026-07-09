import AppKit
import Foundation
import UserNotifications
import WaiComputerKit
import os

private let meetingLog = Logger(subsystem: "is.waiwai.computer.app", category: "meeting-detect")

/// User preference for the "meeting detected" prompt. Same UserDefaults
/// store the Settings toggles use via @AppStorage.
enum MeetingDetectionSettings {
    static let enabledKey = "meetingDetectionEnabled"

    static func isEnabled(defaults: UserDefaults = .standard) -> Bool {
        if defaults.object(forKey: enabledKey) == nil { return true }
        return defaults.bool(forKey: enabledKey)
    }
}

/// Prompts to record when a call starts anywhere on the Mac.
///
/// The industry-standard detection signal (Granola, Notion, Fireflies,
/// Fathom): another app starts capturing the microphone — Zoom, Meet in a
/// browser, FaceTime, Slack huddles. Detection never listens to audio; it
/// reads which processes hold the mic via the CoreAudio process-object API
/// (`MicrophoneUsageWatcher`, macOS 14+, no admin rights needed). Following
/// the same universal pattern, detection only ever produces a notification —
/// recording never starts on its own.
///
/// Runs while the app is idle; transitions that arrive mid-recording or
/// mid-dictation are ignored. Clicking the notification body opens the app;
/// the "Record" action starts a meeting recording immediately.
@MainActor
final class MeetingDetectionController {
    static let categoryIdentifier = "meeting-detection"
    static let startActionIdentifier = "meeting-detection-start"
    static let userInfoKey = "meetingDetection"

    /// Minimum gap between prompts, so one flapping call app cannot spam.
    private let promptCooldown: TimeInterval = 180

    private let center: UNUserNotificationCenter
    /// True while WaiComputer itself owns the session (recording/finalizing) —
    /// a meeting prompt would be noise there.
    private let isBusy: @MainActor () -> Bool
    private var watcher: AnyObject?
    private var lastPromptAt: Date?

    init(
        center: UNUserNotificationCenter = .current(),
        isBusy: @escaping @MainActor () -> Bool
    ) {
        self.center = center
        self.isBusy = isBusy
    }

    func start() {
        guard watcher == nil else { return }
        guard #available(macOS 14.0, *) else {
            meetingLog.info("Meeting detection unavailable before macOS 14")
            return
        }
        let watcher = MicrophoneUsageWatcher()
        watcher.start { [weak self] active, at in
            guard active else { return }
            Task { @MainActor in
                self?.handleCallStarted(at: at)
            }
        }
        self.watcher = watcher
        meetingLog.info("Meeting detection watcher started")
    }

    func stop() {
        if #available(macOS 14.0, *) {
            (watcher as? MicrophoneUsageWatcher)?.stop()
        }
        watcher = nil
    }

    private func handleCallStarted(at date: Date) {
        guard MeetingDetectionSettings.isEnabled() else { return }
        guard !isBusy() else { return }
        if let lastPromptAt, date.timeIntervalSince(lastPromptAt) < promptCooldown {
            return
        }
        lastPromptAt = date
        meetingLog.info("Call started elsewhere — prompting to record")
        deliverPrompt()
    }

    /// The category carries the "Record" action; registered at delivery time
    /// so the action title follows the current UI language.
    private func deliverPrompt() {
        let startAction = UNNotificationAction(
            identifier: Self.startActionIdentifier,
            title: t("Record", "Записать"),
            options: [.foreground]
        )
        let category = UNNotificationCategory(
            identifier: Self.categoryIdentifier,
            actions: [startAction],
            intentIdentifiers: []
        )
        center.setNotificationCategories([category])

        let content = UNMutableNotificationContent()
        content.title = t("Meeting detected", "Похоже, идет встреча")
        content.body = t(
            "Another app is using the microphone. Record this conversation with WaiComputer?",
            "Другое приложение использует микрофон. Записать разговор в WaiComputer?"
        )
        content.sound = .default
        content.categoryIdentifier = Self.categoryIdentifier
        content.userInfo = [Self.userInfoKey: true]
        let request = UNNotificationRequest(
            identifier: "meeting-detection-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )

        center.getNotificationSettings { [center] settings in
            switch settings.authorizationStatus {
            case .authorized, .provisional:
                center.add(request) { error in
                    if let error {
                        meetingLog.error("Prompt scheduling failed: \(error, privacy: .public)")
                    }
                }
            case .notDetermined, .denied:
                meetingLog.info("Skipping meeting prompt: notifications not authorized")
            @unknown default:
                meetingLog.info("Skipping meeting prompt: unsupported authorization status")
            }
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: LanguageManager.shared.current)
    }
}
