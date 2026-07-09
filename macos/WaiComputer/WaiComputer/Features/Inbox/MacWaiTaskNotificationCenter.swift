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
        configure()

        // HIG: request permission in context, tied to a user-visible moment.
        // A Wai turn finishing while the user is in the app is that moment —
        // ask then (no banner needed; they can see the result). A background
        // finish is delivery-only and must never pop the system dialog from
        // another app with zero context.
        guard !application.isActive else {
            requestAuthorizationIfNeeded()
            return
        }

        center.getNotificationSettings { [center] settings in
            switch settings.authorizationStatus {
            case .authorized, .provisional:
                Self.scheduleNotification(center: center, title: title, body: body, chatId: chatId)
            case .notDetermined:
                NSLog("[WaiTaskNotification] Skipping delivery: permission not yet requested in-app")
            case .denied:
                NSLog("[WaiTaskNotification] Authorization denied")
            @unknown default:
                NSLog("[WaiTaskNotification] Unsupported authorization status")
            }
        }
    }

    /// Ask for notification permission only while the app is frontmost, at
    /// the moment a Wai task completes in view — never from the background.
    @MainActor
    private func requestAuthorizationIfNeeded() {
        center.getNotificationSettings { [center] settings in
            guard settings.authorizationStatus == .notDetermined else { return }
            center.requestAuthorization(options: [.alert, .sound]) { granted, error in
                if let error {
                    NSLog("[WaiTaskNotification] Authorization failed: %@", "\(error)")
                    return
                }
                if !granted {
                    NSLog("[WaiTaskNotification] Authorization denied")
                }
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
        let userInfo = response.notification.request.content.userInfo

        if userInfo[MeetingDetectionController.userInfoKey] as? Bool == true {
            let startRecording =
                response.actionIdentifier == MeetingDetectionController.startActionIdentifier
            Task { @MainActor in
                Self.reopenMainWindowIfPossible()
                // The "Record" action starts immediately; a plain click just
                // opens the app with the recording surface ready.
                NotificationCenter.default.post(
                    name: startRecording ? .macStartMeetingRecording : .showNewRecording,
                    object: nil
                )
                completionHandler()
            }
            return
        }

        guard let chatId = userInfo["chatId"] as? String else {
            completionHandler()
            return
        }

        Task { @MainActor in
            Self.reopenMainWindowIfPossible()
            NotificationCenter.default.post(name: .macOpenWaiChat, object: chatId)
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
