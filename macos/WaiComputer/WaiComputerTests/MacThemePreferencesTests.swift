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

    func testDateFormattingUsesSelectedAppLanguage() {
        let date = Date(timeIntervalSince1970: 1_709_292_000)

        let english = MacDateFormatting.string(
            from: date,
            dateStyle: .medium,
            timeStyle: .short,
            language: .english
        )
        let russian = MacDateFormatting.string(
            from: date,
            dateStyle: .medium,
            timeStyle: .short,
            language: .russian
        )

        XCTAssertTrue(english.lowercased().contains("mar"), english)
        XCTAssertTrue(russian.lowercased().contains("мар"), russian)
    }

    func testLongDateFormattingUsesRussianMonthNamesForHistoryHeadings() {
        var components = DateComponents()
        components.calendar = Calendar(identifier: .gregorian)
        components.timeZone = TimeZone(secondsFromGMT: 0)
        components.year = 2026
        components.month = 5
        components.day = 20
        let date = try! XCTUnwrap(components.date)

        let russian = MacDateFormatting.string(
            from: date,
            dateStyle: .long,
            timeStyle: .none,
            language: .russian
        )

        XCTAssertTrue(russian.lowercased().contains("мая"), russian)
        XCTAssertFalse(russian.lowercased().contains("may"), russian)
    }
}
