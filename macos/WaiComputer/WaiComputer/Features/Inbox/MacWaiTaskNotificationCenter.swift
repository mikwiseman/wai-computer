import AppKit
import UserNotifications

final class MacWaiTaskNotificationCenter: NSObject, UNUserNotificationCenterDelegate {
    static let shared = MacWaiTaskNotificationCenter()

    private let center: UNUserNotificationCenter
    private let application: NSApplication
    private var isConfigured = false

    init(
        center: UNUserNotificationCenter = .current(),
        application: NSApplication = .shared
    ) {
        self.center = center
        self.application = application
        super.init()
    }

    func configure() {
        guard !isConfigured else { return }
        center.delegate = self
        isConfigured = true
    }

    @MainActor
    func notifyTaskFinished(title: String, body: String, chatId: String) {
        guard !application.isActive else { return }
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
        guard let chatId = response.notification.request.content.userInfo["chatId"] as? String else {
            completionHandler()
            return
        }

        Task { @MainActor in
            Self.reopenMainWindowIfPossible()
            NotificationCenter.default.post(name: .macOpenInboxChat, object: chatId)
            completionHandler()
        }
    }

    @MainActor
    private static func reopenMainWindowIfPossible() {
        for window in NSApp.windows where window.title == "WaiComputer" {
            window.makeKeyAndOrderFront(nil)
        }
        NSApp.activate(ignoringOtherApps: true)
        MacPresentationCoordinator.shared.mainWindowDidAppear()
    }
}
