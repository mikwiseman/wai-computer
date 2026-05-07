import Foundation
import os

private let langLog = Logger(subsystem: "com.waisay.app", category: "dictation-language")

/// Source of truth for the user's dictation language preference.
///
/// Storage model is a `Set<String>` of BCP-47 codes persisted as a JSON array
/// in UserDefaults under `dictationLanguages`. Three modes derive from the
/// set's cardinality:
///
///   - **0 entries**: auto-detect any language. Wire tag is `""` which
///     ElevenLabs Scribe v2 (and Soniox v4 RT, when re-enabled) treat as
///     multilingual auto-detect.
///   - **1 entry**: single-language mode — send that BCP-47 code as a hint
///     for the lowest possible latency on supported models.
///   - **2+ entries**: multilingual mode — also send `""`. The set is
///     remembered for UI display + future per-model multi-language config
///     (Inworld/Soniox can take multiple language hints; ElevenLabs cannot).
///
/// Migration from the legacy single `transcriptionLanguage` string runs once
/// on first read. The legacy key stays in place so older builds that still
/// read it keep working until they update.
@MainActor
final class DictationLanguageStore: ObservableObject {
    static let userDefaultsKey = "dictationLanguages"
    static let legacyKey = "transcriptionLanguage"

    @Published private(set) var selectedLanguages: Set<String>

    init(defaults: UserDefaults = .standard) {
        self.selectedLanguages = Self.loadOrMigrate(from: defaults)
    }

    /// What we actually send to the upstream STT provider. Empty string for
    /// auto-detect (0 or 2+ languages); the single code for 1-language mode.
    var wireLanguageTag: String {
        if selectedLanguages.count == 1, let only = selectedLanguages.first {
            return only
        }
        return ""
    }

    /// True when the user has not picked any specific language — i.e. the
    /// model auto-detects across all supported languages.
    var isAutoDetect: Bool {
        selectedLanguages.isEmpty
    }

    func setLanguages(_ languages: Set<String>, defaults: UserDefaults = .standard) {
        selectedLanguages = languages
        persist(languages, defaults: defaults)
        langLog.info("Dictation languages updated: \(languages.sorted().joined(separator: ","), privacy: .public)")
    }

    func toggle(_ language: String, defaults: UserDefaults = .standard) {
        var next = selectedLanguages
        if next.contains(language) {
            next.remove(language)
        } else {
            next.insert(language)
        }
        setLanguages(next, defaults: defaults)
    }

    func setAutoDetect(defaults: UserDefaults = .standard) {
        setLanguages([], defaults: defaults)
    }

    // MARK: - Persistence

    private func persist(_ languages: Set<String>, defaults: UserDefaults) {
        let array = Array(languages).sorted()
        if let data = try? JSONEncoder().encode(array) {
            defaults.set(data, forKey: Self.userDefaultsKey)
        }
        // Mirror to legacy single-string key so older code paths reading
        // `transcriptionLanguage` keep working — pick the first entry, or
        // "multi" for auto-detect.
        let legacyValue = languages.count == 1 ? languages.first! : "multi"
        defaults.set(legacyValue, forKey: Self.legacyKey)
    }

    private static func loadOrMigrate(from defaults: UserDefaults) -> Set<String> {
        if let data = defaults.data(forKey: userDefaultsKey),
           let array = try? JSONDecoder().decode([String].self, from: data) {
            return Set(array)
        }
        // First-run migration: read legacy key.
        if let legacy = defaults.string(forKey: legacyKey) {
            switch legacy {
            case "multi", "":
                return []
            default:
                return [legacy]
            }
        }
        return []  // Default to auto-detect if nothing stored.
    }
}

/// Static catalogue of languages exposed in the picker UI. Order is
/// frequency-of-use for the WaiSay user base — English first, Russian second
/// (a top-2 user language), then a Whispr-Flow-style sweep of common picks.
struct DictationLanguageCatalog {
    struct Entry: Hashable, Identifiable {
        let code: String
        let englishName: String
        let nativeName: String
        var id: String { code }
    }

    static let all: [Entry] = [
        .init(code: "en", englishName: "English", nativeName: "English"),
        .init(code: "ru", englishName: "Russian", nativeName: "Русский"),
        .init(code: "es", englishName: "Spanish", nativeName: "Español"),
        .init(code: "de", englishName: "German", nativeName: "Deutsch"),
        .init(code: "fr", englishName: "French", nativeName: "Français"),
        .init(code: "it", englishName: "Italian", nativeName: "Italiano"),
        .init(code: "pt", englishName: "Portuguese", nativeName: "Português"),
        .init(code: "ja", englishName: "Japanese", nativeName: "日本語"),
        .init(code: "zh", englishName: "Chinese", nativeName: "中文"),
        .init(code: "ko", englishName: "Korean", nativeName: "한국어"),
        .init(code: "hi", englishName: "Hindi", nativeName: "हिन्दी"),
        .init(code: "ar", englishName: "Arabic", nativeName: "العربية"),
        .init(code: "uk", englishName: "Ukrainian", nativeName: "Українська"),
        .init(code: "pl", englishName: "Polish", nativeName: "Polski"),
        .init(code: "nl", englishName: "Dutch", nativeName: "Nederlands"),
        .init(code: "tr", englishName: "Turkish", nativeName: "Türkçe"),
    ]

    static func entry(for code: String) -> Entry? {
        all.first { $0.code == code }
    }
}
