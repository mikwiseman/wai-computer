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

    func testListTimestampLabelsTodayAndYesterday() {
        let now = Date()
        let today = MacDateFormatting.listTimestamp(from: now, language: .russian)
        XCTAssertTrue(today.hasPrefix("Сегодня, "), today)

        let yesterday = try! XCTUnwrap(
            Calendar.current.date(byAdding: .day, value: -1, to: now)
        )
        let yesterdayLabel = MacDateFormatting.listTimestamp(from: yesterday, language: .english)
        XCTAssertTrue(yesterdayLabel.hasPrefix("Yesterday, "), yesterdayLabel)
    }

    func testListTimestampDropsRussianYearSuffix() {
        var components = DateComponents()
        components.calendar = Calendar(identifier: .gregorian)
        components.year = 2020
        components.month = 3
        components.day = 8
        components.hour = 9
        components.minute = 5
        let date = try! XCTUnwrap(components.date)

        let russian = MacDateFormatting.listTimestamp(from: date, language: .russian)
        XCTAssertEqual(russian, "8 марта 2020, 09:05")

        let english = MacDateFormatting.listTimestamp(from: date, language: .english)
        XCTAssertTrue(english.contains("March 8, 2020"), english)
    }

    func testDurationRollsMinutesIntoHours() {
        XCTAssertEqual(MacDateFormatting.duration(seconds: 53), "0:53")
        XCTAssertEqual(MacDateFormatting.duration(seconds: 1_720), "28:40")
        // 208 minutes must read as hours, never "208:40".
        XCTAssertEqual(MacDateFormatting.duration(seconds: 12_520), "3:28:40")
        XCTAssertEqual(MacDateFormatting.duration(seconds: 3_600), "1:00:00")
    }
}
