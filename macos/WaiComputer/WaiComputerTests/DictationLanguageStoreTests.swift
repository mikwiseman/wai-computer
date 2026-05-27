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

        let store = DictationLanguageStore(defaults: defaults)

        XCTAssertTrue(store.selectedLanguages.isEmpty)
        XCTAssertEqual(store.wireLanguageTag, "")
    }
}
