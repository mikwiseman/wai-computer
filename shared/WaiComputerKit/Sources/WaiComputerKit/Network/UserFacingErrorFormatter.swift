import Foundation

public enum UserFacingErrorContext: Sendable {
    case generic
    case library
    case recording
    case dictation
    case authentication
}

public enum UserFacingErrorFormatter {
    public static func displayMessage(
        _ message: String?,
        fallback: String,
        context: UserFacingErrorContext = .generic
    ) -> String {
        guard let message else { return fallback }

        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return fallback }
        guard !shouldHideTechnicalMessage(trimmed) else { return fallback }
        return trimmed
    }

    public static func message(
        for error: Error,
        context: UserFacingErrorContext = .generic
    ) -> String {
        if let apiError = error as? APIError {
            return message(for: apiError, context: context)
        }

        if let websocketError = error as? WebSocketConnectionError {
            return message(for: websocketError, context: context)
        }

        let fallback = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        if shouldHideTechnicalMessage(fallback) {
            return genericMessage(for: context)
        }
        return fallback.isEmpty ? genericMessage(for: context) : fallback
    }

    public static func message(
        for error: APIError,
        context: UserFacingErrorContext = .generic
    ) -> String {
        switch error {
        case .unauthorized:
            return "Your session ended. Please sign in again."
        case .networkError:
            return networkMessage(for: context)
        case .httpError(let statusCode, let message):
            if statusCode == 401 {
                return "Your session ended. Please sign in again."
            }
            if let msg = message, !msg.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                if !shouldHideTechnicalMessage(msg) {
                    return msg
                }
            }
            return genericMessage(for: context)
        case .invalidURL, .noData, .decodingError:
            return genericMessage(for: context)
        }
    }

    public static func message(
        for error: WebSocketConnectionError,
        context: UserFacingErrorContext = .generic
    ) -> String {
        switch error {
        case .disconnected,
             .tokenFetchFailed,
             .serverError,
             .invalidURL,
             .reconnectionExhausted:
            return networkMessage(for: context)
        case .superseded:
            return genericMessage(for: context)
        }
    }

    public static func previewMessage(
        _ message: String?,
        context: UserFacingErrorContext = .generic,
        maxLength: Int = 90
    ) -> String? {
        guard let message else { return nil }

        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        let display = shouldHideTechnicalMessage(trimmed)
            ? genericMessage(for: context)
            : trimmed
        let normalized = display.replacingOccurrences(of: "\n", with: " ")

        guard normalized.count > maxLength else { return normalized }
        return String(normalized.prefix(maxLength - 1)) + "…"
    }

    /// The user's chosen interface language.
    ///
    /// These strings reach a Russian-speaking user inside an otherwise fully
    /// Russian UI — the library banner read "We couldn't load your library
    /// right now" on a screen where every other word was Russian. The formatter
    /// is a stateless enum called from a dozen views, so it resolves the
    /// language itself rather than threading a parameter through all of them.
    private static var isRussian: Bool {
        // Read the persisted pick rather than `LanguageManager.shared`, which is
        // main-actor isolated while this formatter is called from background
        // contexts. Falling back to the system language matches what
        // LanguageManager itself does on first launch.
        if let stored = UserDefaults.standard.string(forKey: "waiUserLanguage") {
            return stored.lowercased().hasPrefix("ru")
        }
        return (Locale.preferredLanguages.first ?? "en").lowercased().hasPrefix("ru")
    }

    private static func genericMessage(for context: UserFacingErrorContext) -> String {
        if isRussian {
            switch context {
            case .library:
                return "Не удалось загрузить библиотеку. Попробуй ещё раз через минуту."
            case .recording:
                return "Не удалось сохранить запись. Попробуй ещё раз через минуту."
            case .dictation:
                return "Не удалось завершить диктовку. Попробуй ещё раз."
            case .authentication:
                return "Не удалось выполнить вход. Попробуй ещё раз."
            case .generic:
                return "Что-то пошло не так. Попробуй ещё раз через минуту."
            }
        }
        switch context {
        case .library:
            return "We couldn't load your library right now. Please try again in a moment."
        case .recording:
            return "We couldn't finish saving your recording right now. Please try again in a moment."
        case .dictation:
            return "We couldn't complete dictation right now. Please try again."
        case .authentication:
            return "We couldn't sign you in right now. Please try again."
        case .generic:
            return "Something went wrong. Please try again in a moment."
        }
    }

    private static func networkMessage(for context: UserFacingErrorContext) -> String {
        if isRussian {
            switch context {
            case .recording:
                return "Пропала связь во время записи. Проверь интернет и попробуй ещё раз."
            case .dictation:
                return "Пропала связь во время диктовки. Проверь интернет и попробуй ещё раз."
            case .library:
                return "Не удалось связаться с Wai, чтобы загрузить библиотеку. Проверь интернет."
            case .authentication:
                return "Не удалось связаться с Wai для входа. Проверь интернет и попробуй ещё раз."
            case .generic:
                return "Не удалось связаться с Wai. Проверь интернет и попробуй ещё раз."
            }
        }
        switch context {
        case .recording:
            return "We couldn't keep the live recording connected. Check your internet connection and try again."
        case .dictation:
            return "We couldn't keep dictation connected. Check your internet connection and try again."
        case .library:
            return "We couldn't reach Wai to load your library. Check your internet connection and try again."
        case .authentication:
            return "We couldn't reach Wai to sign you in. Check your internet connection and try again."
        case .generic:
            return "We couldn't reach Wai. Check your internet connection and try again."
        }
    }

    private static func shouldHideTechnicalMessage(_ message: String) -> Bool {
        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return true }

        let lowercased = trimmed.lowercased()
        let technicalFragments = [
            "internal server error",
            "server error (500)",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
            "failed to reconnect after",
            "connection lost after retrying",
            "failed to get transcription token",
            "application support/",
            "/users/",
            "pendingtranscripts",
            "nsurlerrordomain",
            "cfnetwork",
            "nw_connection",
            "json",
            "decoding",
            "socket",
            "timed out",
        ]
        if technicalFragments.contains(where: lowercased.contains) {
            return true
        }

        return trimmed.count > 180
    }
}

public extension Error {
    func userFacingMessage(context: UserFacingErrorContext = .generic) -> String {
        UserFacingErrorFormatter.message(for: self, context: context)
    }
}
