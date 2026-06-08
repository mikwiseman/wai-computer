import UIKit
import UserNotifications

/// Posts a local notification when a Wai agent turn finishes while the app is in
/// the background — the iOS counterpart of `MacWaiTaskNotificationCenter`. The
/// notification hook itself (`onTurnCompleted`) lives in the shared
/// `CompanionView`; only the delivery mechanics differ (UIKit, not AppKit).
/// Tapping the notification routes back to the Wai tab via the existing
/// `navigateTo` notification that `MainTabView` already handles.
final class IOSWaiTaskNotificationCenter: NSObject, UNUserNotificationCenterDelegate {
    static let shared = IOSWaiTaskNotificationCenter()

    private let center: UNUserNotificationCenter
    private var isConfigured = false

    init(center: UNUserNotificationCenter = .current()) {
        self.center = center
        super.init()
    }

    func configure() {
        guard !isConfigured else { return }
        center.delegate = self
        isConfigured = true
    }

    @MainActor
    func notifyTaskFinished(title: String, body: String, chatId: String) {
        // Only fire when the user isn't already looking at the app — an active
        // foreground turn already shows its result inline.
        guard UIApplication.shared.applicationState != .active else { return }
        configure()

        center.getNotificationSettings { [center] settings in
            switch settings.authorizationStatus {
            case .authorized, .provisional:
                Self.scheduleNotification(center: center, title: title, body: body, chatId: chatId)
            case .notDetermined:
                center.requestAuthorization(options: [.alert, .sound]) { granted, error in
                    if let error {
                        NSLog("[WaiTaskNotification] Authorization failed: %@", "\(error)")
                        return
                    }
                    guard granted else {
                        NSLog("[WaiTaskNotification] Authorization denied")
                        return
                    }
                    Self.scheduleNotification(center: center, title: title, body: body, chatId: chatId)
                }
            case .denied:
                NSLog("[WaiTaskNotification] Authorization denied")
            @unknown default:
                NSLog("[WaiTaskNotification] Unsupported authorization status")
            }
        }
    }

    private static func scheduleNotification(
        center: UNUserNotificationCenter,
        title: String,
        body: String,
        chatId: String
    ) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.userInfo = ["chatId": chatId]

        let request = UNNotificationRequest(
            identifier: "wai-agent-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )
        center.add(request) { error in
            if let error {
                NSLog("[WaiTaskNotification] Scheduling failed: %@", "\(error)")
            }
        }
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        Task { @MainActor in
            // Route back to the Wai tab; the just-finished chat is the active one.
            NotificationCenter.default.post(name: .init("navigateTo"), object: "wai")
            completionHandler()
        }
    }
}
