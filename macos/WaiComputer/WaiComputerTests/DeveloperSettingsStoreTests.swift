import XCTest

@MainActor
final class DeveloperSettingsStoreTests: XCTestCase {
    private var suiteName: String!
    private var defaults: UserDefaults!

    override func setUp() async throws {
        // Isolated suite per test — never touch UserDefaults.standard, otherwise
        // an interactive launch after the tests would see polluted values.
        suiteName = "DeveloperSettingsStoreTests-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)
        XCTAssertNotNil(defaults, "Failed to construct test UserDefaults suite")
    }

    override func tearDown() async throws {
        defaults?.removePersistentDomain(forName: suiteName)
        defaults = nil
        suiteName = nil
    }

    func testDefaults() {
        let store = DeveloperSettingsStore(defaults: defaults)
        XCTAssertEqual(store.developerModeEnabled, false)
        XCTAssertEqual(store.dictationProvider, .elevenLabs)
    }

    func testRoundTripPersistsProviderChoice() {
        let storeA = DeveloperSettingsStore(defaults: defaults)
        storeA.dictationProvider = .inworld
        storeA.developerModeEnabled = true

        let storeB = DeveloperSettingsStore(defaults: defaults)
        XCTAssertEqual(storeB.dictationProvider, .inworld)
        XCTAssertEqual(storeB.developerModeEnabled, true)
    }

    func testCorruptValueFallsBackToElevenLabs() {
        defaults.set("not-a-real-provider", forKey: DeveloperSettingsStore.dictationProviderKey)
        let store = DeveloperSettingsStore(defaults: defaults)
        XCTAssertEqual(
            store.dictationProvider,
            .elevenLabs,
            "Garbage rawValue should fall back to default, not crash"
        )
    }

    func testResetClearsProviderButPreservesDeveloperModeToggle() {
        let store = DeveloperSettingsStore(defaults: defaults)
        store.developerModeEnabled = true
        store.dictationProvider = .inworld

        store.reset()

        XCTAssertEqual(store.dictationProvider, .elevenLabs)
        XCTAssertEqual(
            store.developerModeEnabled,
            true,
            "Reset is for dev-only knobs, not the user's intent to be in Developer Mode"
        )
    }

    func testNoOpAssignmentSkipsPersist() {
        let store = DeveloperSettingsStore(defaults: defaults)
        store.dictationProvider = .elevenLabs   // already the default
        // The didSet guard short-circuits when oldValue == newValue, so the
        // raw key should still be absent.
        XCTAssertNil(defaults.string(forKey: DeveloperSettingsStore.dictationProviderKey))
    }
}
