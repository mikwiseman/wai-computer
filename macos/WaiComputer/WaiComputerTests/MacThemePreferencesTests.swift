import SwiftUI
import XCTest

final class MacThemePreferencesTests: XCTestCase {
    private var suiteName: String!
    private var defaults: UserDefaults!

    override func setUpWithError() throws {
        try super.setUpWithError()
        suiteName = "MacThemePreferencesTests.\(UUID().uuidString)"
        defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defaults.removePersistentDomain(forName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        suiteName = nil
        super.tearDown()
    }

    func testAppearanceModeMapsToPreferredColorScheme() {
        XCTAssertNil(MacAppearanceMode.system.preferredColorScheme)
        XCTAssertEqual(MacAppearanceMode.light.preferredColorScheme, .light)
        XCTAssertEqual(MacAppearanceMode.dark.preferredColorScheme, .dark)
    }

    func testPreferencesPersistRawAppearanceAndAccentValues() {
        var preferences = MacThemePreferences(defaults: defaults)

        preferences.appearance = .dark
        preferences.accent = .green

        XCTAssertEqual(defaults.string(forKey: MacThemePreferences.appearanceKey), "dark")
        XCTAssertEqual(defaults.string(forKey: MacThemePreferences.accentKey), "green")
        XCTAssertEqual(MacThemePreferences(defaults: defaults).appearance, .dark)
        XCTAssertEqual(MacThemePreferences(defaults: defaults).accent, .green)
    }

    func testInvalidStoredValuesFallBackToAccessibleDefaults() {
        defaults.set("neon", forKey: MacThemePreferences.appearanceKey)
        defaults.set("invisible", forKey: MacThemePreferences.accentKey)

        let preferences = MacThemePreferences(defaults: defaults)

        XCTAssertEqual(preferences.appearance, .system)
        XCTAssertEqual(preferences.accent, .amber)
    }

    func testAccentChoicesStayCentralizedAndIncludeSystemChoice() {
        XCTAssertEqual(
            MacAccentChoice.allCases.map(\.rawValue),
            ["system", "amber", "blue", "green", "violet", "rose", "graphite"]
        )
        XCTAssertNil(MacAccentChoice.system.tintColor)
        XCTAssertNotNil(MacAccentChoice.amber.tintColor)
    }
}
