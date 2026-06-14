import CryptoKit
import Foundation
import Sentry

public enum SentryHelper {
    private static let fingerprintLock = NSLock()
    private static var capturedFingerprints: [String: Date] = [:]
    static let fingerprintDedupWindow: TimeInterval = 300

    public static func start(dsn: String, debug: Bool = false) {
        guard !dsn.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }

        SentrySDK.start { options in
            options.dsn = dsn
            options.debug = debug
            options.tracesSampleRate = 0.1
            options.profilesSampleRate = 0.1
            options.enableAutoSessionTracking = true
            options.enableCaptureFailedRequests = false
            options.beforeSend = { event in
                sanitizeEventForSentry(event)
            }
            options.beforeBreadcrumb = { breadcrumb in
                sanitizeBreadcrumbForSentry(breadcrumb)
            }
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
        guard SentrySDK.isEnabled else { return }
        SentrySDK.capture(error: error) { scope in
            applyLevelTagsAndExtras(scope, extras: extras)
        }
    }

    public static func captureMessage(
        _ message: String,
        level: SentryLevel = .warning,
        extras: [String: Any]? = nil
    ) {
        guard SentrySDK.isEnabled else { return }
        SentrySDK.capture(message: sanitizeString(message, key: "message")) { scope in
            scope.setLevel(level)
            applyLevelTagsAndExtras(scope, extras: extras)
        }
    }

    public static func captureMessageOnce(
        _ message: String,
        fingerprint: String,
        level: SentryLevel = .warning,
        extras: [String: Any]? = nil
    ) {
        guard SentrySDK.isEnabled else { return }
        guard shouldCaptureFingerprint(fingerprint) else { return }
        captureMessage(message, level: level, extras: extras)
    }

    private static func applyLevelTagsAndExtras(_ scope: Scope, extras: [String: Any]?) {
        if let extras {
            let sanitized = sanitizeDictionary(extras)
            for (key, value) in sanitized {
                scope.setExtra(value: value, key: key)
            }
            for key in ["alert_code", "provider", "model", "platform", "purpose", "failure_code", "statusCode"] {
                if let value = sanitized[key] {
                    scope.setTag(value: "\(value)", key: key)
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
        guard SentrySDK.isEnabled else { return }
        let crumb = Breadcrumb(level: level, category: category)
        crumb.message = sanitizeString(message, key: "message")
        if let data {
            crumb.data = sanitizeDictionary(data)
        }
        SentrySDK.addBreadcrumb(crumb)
    }

    public static func setUser(id: String) {
        guard SentrySDK.isEnabled else { return }
        let user = Sentry.User()
        user.userId = id
        SentrySDK.setUser(user)
    }

    public static func clearUser() {
        guard SentrySDK.isEnabled else { return }
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

    static func sanitizeEventForSentry(_ event: Event) -> Event {
        if let message = event.message {
            let sanitizedFormatted = sanitizeString(message.formatted, key: "message")
            let sanitizedMessage = SentryMessage(formatted: sanitizedFormatted)
            if let rawMessage = message.message {
                sanitizedMessage.message = sanitizeString(rawMessage, key: "message")
            }
            if let params = message.params {
                sanitizedMessage.params = params.map { sanitizeString($0, key: "message") }
            }
            event.message = sanitizedMessage
        }

        if let tags = event.tags {
            event.tags = tags.mapValues { sanitizeString($0, key: nil) }
        }
        if let extra = event.extra {
            event.extra = sanitizeDictionary(extra)
        }
        if let context = event.context {
            event.context = sanitizeDictionary(context) as? [String: [String: Any]]
        }
        if let user = event.user {
            user.email = nil
            user.username = nil
            user.ipAddress = nil
            user.name = nil
            if let data = user.data {
                user.data = sanitizeDictionary(data)
            }
        }
        if let request = event.request {
            request.url = request.url.map(stripQueryAndFragment)
            request.queryString = nil
            request.cookies = nil
            if let headers = request.headers {
                request.headers = Dictionary(
                    uniqueKeysWithValues: headers.map { key, value in
                        (key, sanitizeString(value, key: key))
                    }
                )
            }
        }
        if let breadcrumbs = event.breadcrumbs {
            event.breadcrumbs = breadcrumbs.compactMap(sanitizeBreadcrumbForSentry)
        }
        return event
    }

    static func sanitizeBreadcrumbForSentry(_ breadcrumb: Breadcrumb) -> Breadcrumb? {
        if let message = breadcrumb.message {
            breadcrumb.message = sanitizeString(message, key: "message")
        }
        if let data = breadcrumb.data {
            breadcrumb.data = sanitizeDictionary(data)
        }
        return breadcrumb
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
        var result = value

        let replacements: [(String, NSRegularExpression.Options, (String) -> String)] = [
            (
                "[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}",
                [.caseInsensitive],
                { "[redacted-email:\(fingerprint($0.lowercased()))]" }
            ),
            (
                "\\beyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}\\b",
                [],
                { _ in "[redacted-token]" }
            ),
            (
                "(https://api\\.telegram\\.org/(?:file/)?bot)[^/\\s\\\"']+",
                [],
                { match in
                    if let prefixRange = match.range(of: "bot") {
                        return String(match[..<prefixRange.upperBound]) + "[redacted-token]"
                    }
                    return "[redacted-token]"
                }
            ),
            (
                "\\b[Bb]earer\\s+[A-Za-z0-9._-]{20,}\\b",
                [],
                { _ in "Bearer [redacted-token]" }
            ),
            (
                "(?i)([?&]?)(token|api_key|key|secret|authorization|password)=([^&#\\s\\\"']+)",
                [],
                { match in
                    guard let equals = match.firstIndex(of: "=") else {
                        return "[redacted-secret]"
                    }
                    return String(match[...equals]) + "[redacted-secret]"
                }
            ),
        ]

        for (pattern, options, replacement) in replacements {
            guard let regex = try? NSRegularExpression(pattern: pattern, options: options) else {
                continue
            }
            let range = NSRange(result.startIndex..<result.endIndex, in: result)
            for match in regex.matches(in: result, options: [], range: range).reversed() {
                guard let matchRange = Range(match.range, in: result) else { continue }
                result.replaceSubrange(matchRange, with: replacement(String(result[matchRange])))
            }
        }

        return result
    }

    private static func stripQueryAndFragment(_ value: String) -> String {
        guard var components = URLComponents(string: value) else { return redactEmbeddedSecrets(in: value) }
        components.query = nil
        components.fragment = nil
        return components.string ?? redactEmbeddedSecrets(in: value)
    }
}
