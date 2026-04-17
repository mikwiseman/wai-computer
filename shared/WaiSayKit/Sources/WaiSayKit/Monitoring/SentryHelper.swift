import CryptoKit
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
                for (key, value) in sanitizeDictionary(extras) {
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
        crumb.message = sanitizeString(message, key: "message")
        if let data {
            crumb.data = sanitizeDictionary(data)
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

    static func sanitizeDictionary(_ values: [String: Any]) -> [String: Any] {
        var sanitized: [String: Any] = [:]
        for (key, value) in values {
            sanitized[key] = sanitizeValue(value, key: key)
        }
        return sanitized
    }

    static func sanitizeValue(_ value: Any, key: String? = nil) -> Any {
        if let dictionary = value as? [String: Any] {
            return sanitizeDictionary(dictionary)
        }

        if let array = value as? [Any] {
            return array.map { sanitizeValue($0, key: key) }
        }

        if let string = value as? String {
            return sanitizeString(string, key: key)
        }

        if let data = value as? Data {
            return "<bytes:\(data.count)>"
        }

        return value
    }

    static func sanitizeString(_ value: String, key: String? = nil) -> String {
        let normalizedKey = key?.lowercased() ?? ""
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)

        if containsAny(normalizedKey, fragments: ["token", "password", "secret", "authorization", "cookie"]) {
            return "[redacted-secret]"
        }
        if containsAny(normalizedKey, fragments: ["email"]) {
            return "[redacted-email:\(fingerprint(trimmed.lowercased()))]"
        }
        if containsAny(normalizedKey, fragments: ["filename", "file_name"]) {
            let ext = URL(fileURLWithPath: trimmed).pathExtension.lowercased()
            return "[redacted-filename:ext=\(ext.isEmpty ? "none" : ext):sha=\(fingerprint(trimmed)):len=\(trimmed.count)]"
        }
        if containsAny(normalizedKey, fragments: ["query", "question", "text", "content", "transcript", "body", "html", "prompt", "reason", "error", "detail", "description"]) {
            return "[redacted-text:len=\(trimmed.count):sha=\(fingerprint(trimmed))]"
        }

        return redactEmbeddedSecrets(in: value)
    }

    private static func containsAny(_ key: String, fragments: [String]) -> Bool {
        fragments.contains { key.contains($0) }
    }

    private static func fingerprint(_ value: String) -> String {
        guard !value.isEmpty else { return "-" }
        let digest = SHA256.hash(data: Data(value.utf8))
        return digest.compactMap { String(format: "%02x", $0) }.joined().prefix(12).description
    }

    private static func redactEmbeddedSecrets(in value: String) -> String {
        guard let emailRegex = try? NSRegularExpression(
            pattern: "[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}",
            options: [.caseInsensitive]
        ) else {
            return value
        }

        let range = NSRange(value.startIndex..<value.endIndex, in: value)
        var result = value

        for match in emailRegex.matches(in: value, options: [], range: range).reversed() {
            guard let matchRange = Range(match.range, in: result) else { continue }
            let email = String(result[matchRange]).lowercased()
            result.replaceSubrange(
                matchRange,
                with: "[redacted-email:\(fingerprint(email))]"
            )
        }

        return result
    }
}
