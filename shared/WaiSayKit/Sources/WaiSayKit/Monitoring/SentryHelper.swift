import Foundation
import Sentry

public enum SentryHelper {
    public static func start(dsn: String, debug: Bool = false) {
        SentrySDK.start { options in
            options.dsn = dsn
            options.debug = debug
            options.tracesSampleRate = 0.1
            options.profilesSampleRate = 0.1
            options.enableAutoSessionTracking = true
            options.enableCaptureFailedRequests = true
            #if canImport(UIKit)
            options.attachScreenshot = false
            #endif
            options.sendDefaultPii = false
            #if DEBUG
            options.environment = "development"
            #else
            options.environment = "production"
            #endif
        }
    }

    public static func captureError(_ error: Error, extras: [String: Any]? = nil) {
        SentrySDK.capture(error: error) { scope in
            if let extras {
                for (key, value) in extras {
                    scope.setExtra(value: value, key: key)
                }
            }
        }
    }

    public static func addBreadcrumb(
        category: String,
        message: String,
        level: SentryLevel = .info,
        data: [String: Any]? = nil
    ) {
        let crumb = Breadcrumb(level: level, category: category)
        crumb.message = message
        if let data {
            crumb.data = data
        }
        SentrySDK.addBreadcrumb(crumb)
    }

    public static func setUser(id: String) {
        let user = Sentry.User()
        user.userId = id
        SentrySDK.setUser(user)
    }

    public static func clearUser() {
        SentrySDK.setUser(nil)
    }
}
