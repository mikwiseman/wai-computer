import XCTest

@MainActor
final class TranslationLanguageStoreTests: XCTestCase {
    private var suiteName: String!
    private var defaults: UserDefaults!

    override func setUpWithError() throws {
        try super.setUpWithError()
        suiteName = "TranslationLanguageStoreTests.\(UUID().uuidString)"
        defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defaults.removePersistentDomain(forName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        suiteName = nil
        super.tearDown()
    }

    func testFreshStoreHasSingleDefaultTarget() {
        let store = TranslationLanguageStore(defaults: defaults)

        XCTAssertEqual(store.enabledLanguageCodes, [store.selectedLanguageCode])
        XCTAssertEqual(
            defaults.stringArray(forKey: TranslationLanguageStore.enabledTargetsKey),
            store.enabledLanguageCodes
        )
    }

    func testMigratesLegacySingleTargetIntoEnabledList() {
        defaults.set("de", forKey: TranslationLanguageStore.userDefaultsKey)

        let store = TranslationLanguageStore(defaults: defaults)

        XCTAssertEqual(store.selectedLanguageCode, "de")
        XCTAssertEqual(store.enabledLanguageCodes, ["de"])
    }

    func testEnableLanguageAppendsPreservingOrder() {
        defaults.set("en", forKey: TranslationLanguageStore.userDefaultsKey)
        let store = TranslationLanguageStore(defaults: defaults)

        store.enableLanguage("es", defaults: defaults)
        store.enableLanguage("ja", defaults: defaults)
        store.enableLanguage("es", defaults: defaults) // duplicate is a no-op

        XCTAssertEqual(store.enabledLanguageCodes, ["en", "es", "ja"])
        XCTAssertEqual(store.selectedLanguageCode, "en")
        XCTAssertEqual(
            defaults.stringArray(forKey: TranslationLanguageStore.enabledTargetsKey),
            ["en", "es", "ja"]
        )
    }

    func testSelectLanguageSwitchesAmongEnabledTargets() {
        defaults.set("en", forKey: TranslationLanguageStore.userDefaultsKey)
        let store = TranslationLanguageStore(defaults: defaults)
        store.enableLanguage("fr", defaults: defaults)

        store.selectLanguage("fr", defaults: defaults)

        XCTAssertEqual(store.selectedLanguageCode, "fr")
        XCTAssertEqual(defaults.string(forKey: TranslationLanguageStore.userDefaultsKey), "fr")
    }

    func testSelectUnknownCodeIsIgnored() {
        let store = TranslationLanguageStore(defaults: defaults)
        let before = store.selectedLanguageCode

        store.selectLanguage("xx", defaults: defaults)

        XCTAssertEqual(store.selectedLanguageCode, before)
    }

    func testSelectingUnenabledCatalogLanguageEnablesIt() {
        defaults.set("en", forKey: TranslationLanguageStore.userDefaultsKey)
        let store = TranslationLanguageStore(defaults: defaults)

        store.selectLanguage("it", defaults: defaults)

        XCTAssertEqual(store.selectedLanguageCode, "it")
        XCTAssertEqual(store.enabledLanguageCodes, ["en", "it"])
    }

    func testDisableLanguageKeepsAtLeastOneAndMovesSelection() {
        defaults.set("en", forKey: TranslationLanguageStore.userDefaultsKey)
        let store = TranslationLanguageStore(defaults: defaults)
        store.enableLanguage("de", defaults: defaults)
        store.selectLanguage("de", defaults: defaults)

        store.disableLanguage("de", defaults: defaults)

        XCTAssertEqual(store.enabledLanguageCodes, ["en"])
        XCTAssertEqual(store.selectedLanguageCode, "en")

        // The last remaining target cannot be disabled.
        store.disableLanguage("en", defaults: defaults)
        XCTAssertEqual(store.enabledLanguageCodes, ["en"])
    }

    func testMoveEnabledLanguageReorders() {
        defaults.set("en", forKey: TranslationLanguageStore.userDefaultsKey)
        let store = TranslationLanguageStore(defaults: defaults)
        store.enableLanguage("es", defaults: defaults)
        store.enableLanguage("ja", defaults: defaults)

        store.moveEnabledLanguages(fromOffsets: IndexSet(integer: 2), toOffset: 0, defaults: defaults)

        XCTAssertEqual(store.enabledLanguageCodes, ["ja", "en", "es"])
    }

    func testSelectNextTargetCyclesInOrder() {
        defaults.set("en", forKey: TranslationLanguageStore.userDefaultsKey)
        let store = TranslationLanguageStore(defaults: defaults)
        store.enableLanguage("es", defaults: defaults)
        store.enableLanguage("ja", defaults: defaults)

        store.selectNextTarget(defaults: defaults)
        XCTAssertEqual(store.selectedLanguageCode, "es")
        store.selectNextTarget(defaults: defaults)
        XCTAssertEqual(store.selectedLanguageCode, "ja")
        store.selectNextTarget(defaults: defaults)
        XCTAssertEqual(store.selectedLanguageCode, "en")
    }

    func testDropsUnknownCodesFromPersistedList() {
        defaults.set(["en", "xx", "de"], forKey: TranslationLanguageStore.enabledTargetsKey)
        defaults.set("en", forKey: TranslationLanguageStore.userDefaultsKey)

        let store = TranslationLanguageStore(defaults: defaults)

        XCTAssertEqual(store.enabledLanguageCodes, ["en", "de"])
    }
}
