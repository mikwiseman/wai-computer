import CryptoKit
import Foundation
import Sentry

public enum SentryHelper {
    private static let fingerprintLock = NSLock()
    private static var capturedFingerprints: [String: Date] = [:]
    static let fingerprintDedupWindow: TimeInterval = 300

    public static func start(dsn: String, debug: Bool = false) {
        SentrySDK.start { options in
            options.dsn = dsn
            options.debug = debug
            options.tracesSampleRate = 0.1
            options.profilesSampleRate = 0.1
            options.enableAutoSessionTracking = true
            options.enableCaptureFailedRequests = false
            // App Hang detection produces high-volume events that the team
            // already reviews via custom telemetry — opt out of the SDK path
            // to keep the Sentry events quota for actionable failures.
            options.enableAppHangTracking = false
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

    public static func captureErrorOnce(
        _ error: Error,
        fingerprint: String,
        extras: [String: Any]? = nil
    ) {
        guard shouldCaptureFingerprint(fingerprint) else { return }
        captureError(error, extras: extras)
    }

    public static func captureRequestFailure(
        _ error: Error,
        method: String,
        path: String,
        extras: [String: Any]? = nil
    ) {
        let normalizedPath = normalizedRequestPath(path)
        var mergedExtras = extras ?? [:]
        mergedExtras["method"] = method
        mergedExtras["path"] = normalizedPath

        if let apiError = error as? APIError {
            switch apiError {
            case .unauthorized:
                addBreadcrumb(
                    category: "api",
                    message: "request unauthorized",
                    level: .warning,
                    data: mergedExtras
                )
                return
            case .httpError(let statusCode, _):
                mergedExtras["statusCode"] = statusCode
                if statusCode < 500 {
                    addBreadcrumb(
                        category: "api",
                        message: "request failed",
                        level: .warning,
                        data: mergedExtras
                    )
                    return
                }
                captureErrorOnce(
                    apiError,
                    fingerprint: requestFingerprint(
                        method: method,
                        path: normalizedPath,
                        kind: "http_\(statusCode)"
                    ),
                    extras: mergedExtras
                )
            case .networkError(let underlying):
                if let urlError = underlying as? URLError {
                    mergedExtras["urlErrorCode"] = urlError.code.rawValue
                }
                captureErrorOnce(
                    apiError,
                    fingerprint: requestFingerprint(
                        method: method,
                        path: normalizedPath,
                        kind: "network"
                    ),
                    extras: mergedExtras
                )
            case .decodingError, .invalidURL, .noData:
                captureErrorOnce(
                    apiError,
                    fingerprint: requestFingerprint(
                        method: method,
                        path: normalizedPath,
                        kind: "client"
                    ),
                    extras: mergedExtras
                )
            }
            return
        }

        if let urlError = error as? URLError {
            mergedExtras["urlErrorCode"] = urlError.code.rawValue
            // -999 (.cancelled) and -1001 (.timedOut) come from user navigation
            // and transient network blips — they swamp the events quota
            // without representing actionable failures.
            if urlError.code == .cancelled || urlError.code == .timedOut {
                addBreadcrumb(
                    category: "api",
                    message: "request \(urlError.code == .cancelled ? "cancelled" : "timed out")",
                    level: .warning,
                    data: mergedExtras
                )
                return
            }
            captureErrorOnce(
                urlError,
                fingerprint: requestFingerprint(
                    method: method,
                    path: normalizedPath,
                    kind: "url_\(urlError.code.rawValue)"
                ),
                extras: mergedExtras
            )
            return
        }

        captureErrorOnce(
            error,
            fingerprint: requestFingerprint(
                method: method,
                path: normalizedPath,
                kind: String(describing: type(of: error))
            ),
            extras: mergedExtras
        )
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

    static func normalizedRequestPath(_ path: String) -> String {
        let components = path.split(separator: "/", omittingEmptySubsequences: false).map {
            normalizePathComponent(String($0))
        }

        if path.hasPrefix("/") {
            return "/" + components.dropFirst().joined(separator: "/")
        }

        return components.joined(separator: "/")
    }

    static func requestFingerprint(method: String, path: String, kind: String) -> String {
        "request:\(method.uppercased()):\(path):\(kind)"
    }

    static func shouldCaptureFingerprint(_ fingerprint: String) -> Bool {
        shouldCaptureFingerprint(fingerprint, now: Date())
    }

    static func shouldCaptureFingerprint(_ fingerprint: String, now: Date) -> Bool {
        fingerprintLock.lock()
        defer { fingerprintLock.unlock() }

        let cutoff = now.addingTimeInterval(-fingerprintDedupWindow)
        capturedFingerprints = capturedFingerprints.filter { $0.value > cutoff }

        if let capturedAt = capturedFingerprints[fingerprint], capturedAt > cutoff {
            return false
        }

        capturedFingerprints[fingerprint] = now
        return true
    }

    static func resetCapturedFingerprints() {
        fingerprintLock.lock()
        defer { fingerprintLock.unlock() }
        capturedFingerprints.removeAll()
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

    private static func normalizePathComponent(_ component: String) -> String {
        guard !component.isEmpty else { return component }
        if UUID(uuidString: component) != nil {
            return ":id"
        }
        if component.range(of: #"^[0-9]{6,}$"#, options: .regularExpression) != nil {
            return ":id"
        }
        if component.range(of: #"^[0-9A-HJKMNP-TV-Z]{26}$"#, options: .regularExpression) != nil {
            return ":id"
        }
        return component
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
