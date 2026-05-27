import XCTest

@MainActor
final class DictationLanguageStoreTests: XCTestCase {
    private var suiteName: String!
    private var defaults: UserDefaults!

    override func setUpWithError() throws {
        try super.setUpWithError()
        suiteName = "DictationLanguageStoreTests.\(UUID().uuidString)"
        defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defaults.removePersistentDomain(forName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        suiteName = nil
        super.tearDown()
    }

    func testDefaultIsAutoDetect() {
        let store = DictationLanguageStore(defaults: defaults)

        XCTAssertTrue(store.selectedLanguages.isEmpty)
        XCTAssertEqual(store.wireLanguageTag, "")
        XCTAssertEqual(defaults.string(forKey: DictationLanguageStore.legacyKey), "multi")
    }

    func testSelectingLanguagePersistsSingleOpenAIHint() {
        let store = DictationLanguageStore(defaults: defaults)

        store.toggle("ru", defaults: defaults)

        XCTAssertEqual(store.selectedLanguages, ["ru"])
        XCTAssertEqual(store.wireLanguageTag, "ru")
        XCTAssertEqual(defaults.string(forKey: DictationLanguageStore.legacyKey), "ru")
    }

    func testSelectingAnotherLanguageReplacesPreviousSelection() {
        let store = DictationLanguageStore(defaults: defaults)

        store.toggle("ru", defaults: defaults)
        store.toggle("en", defaults: defaults)

        XCTAssertEqual(store.selectedLanguages, ["en"])
        XCTAssertEqual(store.wireLanguageTag, "en")
        XCTAssertEqual(defaults.string(forKey: DictationLanguageStore.legacyKey), "en")
    }

    func testTogglingSelectedLanguageReturnsToAutoDetect() {
        let store = DictationLanguageStore(defaults: defaults)

        store.toggle("en", defaults: defaults)
        store.toggle("en", defaults: defaults)

        XCTAssertTrue(store.selectedLanguages.isEmpty)
        XCTAssertEqual(store.wireLanguageTag, "")
        XCTAssertEqual(defaults.string(forKey: DictationLanguageStore.legacyKey), "multi")
    }

    func testLegacyMultiselectStorageMigratesToAutoDetect() throws {
        let encoded = try JSONEncoder().encode(["en", "ru"])
        defaults.set(encoded, forKey: DictationLanguageStore.userDefaultsKey)
        defaults.set("ru", forKey: DictationLanguageStore.legacyKey)

        let store = DictationLanguageStore(defaults: defaults)

        XCTAssertTrue(store.selectedLanguages.isEmpty)
        XCTAssertEqual(store.wireLanguageTag, "")
        XCTAssertEqual(defaults.string(forKey: DictationLanguageStore.legacyKey), "multi")
        let persisted = try XCTUnwrap(defaults.data(forKey: DictationLanguageStore.userDefaultsKey))
        let decoded = try JSONDecoder().decode([String].self, from: persisted)
        XCTAssertEqual(decoded, [])
    }

    func testProviderLanguageUsesSelectedStoreBeforeStaleLegacyKey() {
        defaults.set("ru", forKey: DictationLanguageStore.legacyKey)
        let store = DictationLanguageStore(defaults: defaults)

        store.toggle("en", defaults: defaults)

        XCTAssertEqual(
            DictationLanguageSelectionPolicy.providerLanguage(store: store, defaults: defaults),
            "en"
        )
    }

    func testProviderLanguageNormalizesLegacyValueWhenStoreIsUnavailable() {
        defaults.set(" RU ", forKey: DictationLanguageStore.legacyKey)

        XCTAssertEqual(
            DictationLanguageSelectionPolicy.providerLanguage(store: nil, defaults: defaults),
            "ru"
        )
    }

    func testProviderLanguageTreatsBlankLegacyValueAsAutoDetect() {
        defaults.set("  ", forKey: DictationLanguageStore.legacyKey)

        XCTAssertEqual(
            DictationLanguageSelectionPolicy.providerLanguage(store: nil, defaults: defaults),
            "multi"
        )
    }

    func testInitialSettingsIngestDoesNotClearPrefetchedRealtimeConfig() {
        XCTAssertFalse(
            DictationSessionConfigInvalidationPolicy.shouldClearVault(
                previousProvider: nil,
                previousModel: nil,
                nextProvider: "openai",
                nextModel: "gpt-realtime-whisper"
            )
        )
    }

    func testSettingsIngestClearsRealtimeConfigOnlyWhenProviderOrModelChanges() {
        XCTAssertFalse(
            DictationSessionConfigInvalidationPolicy.shouldClearVault(
                previousProvider: "openai",
                previousModel: "gpt-realtime-whisper",
                nextProvider: "openai",
                nextModel: "gpt-realtime-whisper"
            )
        )
        XCTAssertTrue(
            DictationSessionConfigInvalidationPolicy.shouldClearVault(
                previousProvider: "openai",
                previousModel: "legacy-live",
                nextProvider: "openai",
                nextModel: "gpt-realtime-whisper"
            )
        )
    }
}
