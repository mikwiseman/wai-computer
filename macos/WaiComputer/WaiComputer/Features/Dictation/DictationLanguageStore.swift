import Foundation
import os

private let langLog = Logger(subsystem: "is.waiwai.computer.app", category: "dictation-language")

/// Source of truth for the user's dictation language preference.
///
/// Storage model is a `Set<String>` of BCP-47 codes persisted as a JSON array
/// in UserDefaults under `dictationLanguages`. Two modes derive from the set's
/// cardinality:
///
///   - **0 entries**: multilingual auto-detect. Wire tag is `""`; provider
///     adapters send the provider's explicit multilingual mode.
///   - **1 entry**: single-language mode — send that BCP-47 code as a hint
///     for the lowest possible latency on supported models.
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
        let loaded = Self.loadOrMigrate(from: defaults)
        self.selectedLanguages = loaded
        Self.persist(loaded, defaults: defaults)
    }

    /// What we actually send to the upstream STT provider. Empty string for
    /// auto-detect; the single code for 1-language mode.
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
        let normalized = Self.normalizedSelection(languages)
        selectedLanguages = normalized
        persist(normalized, defaults: defaults)
        langLog.info("Dictation languages updated: \(normalized.sorted().joined(separator: ","), privacy: .public)")
    }

    func toggle(_ language: String, defaults: UserDefaults = .standard) {
        guard let normalized = Self.normalizedLanguage(language) else { return }
        if selectedLanguages == [normalized] {
            setAutoDetect(defaults: defaults)
        } else {
            setLanguages([normalized], defaults: defaults)
        }
    }

    func setAutoDetect(defaults: UserDefaults = .standard) {
        setLanguages([], defaults: defaults)
    }

    // MARK: - Persistence

    private func persist(_ languages: Set<String>, defaults: UserDefaults) {
        Self.persist(languages, defaults: defaults)
    }

    private static func persist(_ languages: Set<String>, defaults: UserDefaults) {
        let array = Array(languages).sorted()
        if let data = try? JSONEncoder().encode(array) {
            defaults.set(data, forKey: Self.userDefaultsKey)
        }
        // Mirror to legacy single-string key so older code paths reading
        // `transcriptionLanguage` keep working.
        let legacyValue = languages.count == 1 ? languages.first! : "multi"
        defaults.set(legacyValue, forKey: Self.legacyKey)
    }

    private static func loadOrMigrate(from defaults: UserDefaults) -> Set<String> {
        if let data = defaults.data(forKey: userDefaultsKey),
           let array = try? JSONDecoder().decode([String].self, from: data) {
            return normalizedSelection(Set(array))
        }
        // First-run migration: read legacy key.
        if let legacy = defaults.string(forKey: legacyKey) {
            switch legacy {
            case "multi", "":
                return []
            default:
                return normalizedSelection([legacy])
            }
        }
        return []  // Default to auto-detect if nothing stored.
    }

    private static func normalizedSelection(_ languages: Set<String>) -> Set<String> {
        let cleaned = Set(languages.compactMap(normalizedLanguage))
        guard cleaned.count == 1, let only = cleaned.first else { return [] }
        return [only]
    }

    private static func normalizedLanguage(_ language: String) -> String? {
        let normalized = language.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return normalized.isEmpty || normalized == "multi" || normalized == "auto" ? nil : normalized
    }
}

@MainActor
enum DictationLanguageSelectionPolicy {
    static func providerLanguage(
        store: DictationLanguageStore?,
        defaults: UserDefaults = .standard
    ) -> String {
        if let store {
            return providerLanguage(fromWireTag: store.wireLanguageTag)
        }
        return providerLanguage(
            fromWireTag: defaults.string(forKey: DictationLanguageStore.legacyKey)
        )
    }

    static func providerLanguage(fromWireTag tag: String?) -> String {
        guard let normalized = normalizedProviderLanguage(tag) else {
            return "multi"
        }
        return normalized
    }

    private static func normalizedProviderLanguage(_ language: String?) -> String? {
        guard let language else { return nil }
        let normalized = language.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return normalized.isEmpty || normalized == "multi" || normalized == "auto" ? nil : normalized
    }
}

enum DictationSessionConfigInvalidationPolicy {
    static func shouldClearVault(
        previousProvider: String?,
        previousModel: String?,
        nextProvider: String,
        nextModel: String
    ) -> Bool {
        guard let previousProvider, let previousModel else { return false }
        return previousProvider != nextProvider || previousModel != nextModel
    }
}

/// Static catalogue of languages exposed in the picker UI. Order is
/// frequency-of-use for the WaiComputer user base — English first, Russian second
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
