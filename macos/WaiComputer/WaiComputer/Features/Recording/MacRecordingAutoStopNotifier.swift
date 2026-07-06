import AppKit
import UserNotifications

/// System notifications for the conversation auto-stop flow.
///
/// The in-app banner owns the interaction while WaiComputer is frontmost;
/// notifications exist for the main real-world case — the user left the desk
/// or switched apps after the call ended. Clicking one activates the app,
/// where the live prompt (or the finished recording) is waiting.
final class MacRecordingAutoStopNotifier {
    static let shared = MacRecordingAutoStopNotifier()

    private let center: UNUserNotificationCenter
    private let application: NSApplication

    init(
        center: UNUserNotificationCenter = .current(),
        application: NSApplication = .shared
    ) {
        self.center = center
        self.application = application
    }

    /// Ask for notification permission at recording start — a user-initiated,
    /// in-context moment (HIG) — so the end-of-conversation prompt can reach
    /// the user later even if they walk away.
    @MainActor
    func requestAuthorizationIfNeeded() {
        guard application.isActive else { return }
        center.getNotificationSettings { [center] settings in
            guard settings.authorizationStatus == .notDetermined else { return }
            center.requestAuthorization(options: [.alert, .sound]) { granted, error in
                if let error {
                    NSLog("[RecordingAutoStop] Authorization failed: %@", "\(error)")
                } else if !granted {
                    NSLog("[RecordingAutoStop] Authorization denied")
                }
            }
        }
    }

    @MainActor
    func notifyPromptIfInactive(title: String, body: String) {
        deliverIfInactive(identifier: "recording-autostop-prompt", title: title, body: body)
    }

    @MainActor
    func notifyAutoActionIfInactive(title: String, body: String) {
        deliverIfInactive(identifier: "recording-autostop-action", title: title, body: body)
    }

    /// While the app is frontmost the live banner is the interaction surface;
    /// a parallel system banner would just duplicate it.
    @MainActor
    private func deliverIfInactive(identifier: String, title: String, body: String) {
        guard !application.isActive else { return }
        center.getNotificationSettings { [center] settings in
            switch settings.authorizationStatus {
            case .authorized, .provisional:
                let content = UNMutableNotificationContent()
                content.title = title
                content.body = body
                content.sound = .default
                let request = UNNotificationRequest(
                    identifier: "\(identifier)-\(UUID().uuidString)",
                    content: content,
                    trigger: nil
                )
                center.add(request) { error in
                    if let error {
                        NSLog("[RecordingAutoStop] Scheduling failed: %@", "\(error)")
                    }
                }
            case .notDetermined, .denied:
                NSLog("[RecordingAutoStop] Skipping notification: not authorized")
            @unknown default:
                NSLog("[RecordingAutoStop] Unsupported authorization status")
            }
        }
    }
}
