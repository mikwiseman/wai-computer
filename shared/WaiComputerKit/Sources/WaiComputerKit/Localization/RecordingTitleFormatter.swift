import Foundation

/// Immediate, deterministic identity for a live recording while its final
/// transcript is still being prepared. The server may replace it once when
/// automatic naming is enabled; otherwise it remains useful on its own.
public enum RecordingTitleFormatter {
    public static func provisionalTitle(
        at date: Date = Date(),
        language: OnboardingL10n.Language,
        timeZone: TimeZone = .current
    ) -> String {
        let formatter = DateFormatter()
        formatter.timeZone = timeZone

        switch language {
        case .english:
            formatter.locale = Locale(identifier: "en_US")
            formatter.dateFormat = "MMM d, yyyy, h:mm a"
            return "Recording · \(formatter.string(from: date))"
        case .russian:
            formatter.locale = Locale(identifier: "ru_RU")
            formatter.dateFormat = "dd.MM.yyyy, HH:mm"
            return "Запись · \(formatter.string(from: date))"
        }
    }
}
