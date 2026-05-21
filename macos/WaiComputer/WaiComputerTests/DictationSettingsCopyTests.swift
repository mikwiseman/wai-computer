import WaiComputerKit
import XCTest

final class DictationSettingsCopyTests: XCTestCase {
    func testFreshInstallPushToTalkDefaultIsRightCommand() {
        XCTAssertEqual(DictationHotkey.defaultPushToTalk, .rightCommand)
    }

    @MainActor
    func testHotkeyManagerUsesRightCommandBeforeConfiguration() {
        XCTAssertEqual(GlobalHotkeyManager().hotkey, .rightCommand)
    }

    func testHotkeyLabelsUseRussianCopyInSettings() {
        XCTAssertEqual(
            DictationSettingsCopy.hotkeyLabel(rawValue: "right_command", language: .russian),
            "Правый Command (\u{2318})"
        )
        XCTAssertEqual(
            DictationSettingsCopy.hotkeyLabel(rawValue: "fn", language: .russian),
            "Fn (Глобус)"
        )
    }

    func testHotkeyShortLabelsUseRussianCopyInSettingsHints() {
        XCTAssertEqual(
            DictationSettingsCopy.hotkeyShortLabel(rawValue: "right_option", language: .russian),
            "\u{2325} справа"
        )
        XCTAssertEqual(
            DictationSettingsCopy.hotkeyShortLabel(rawValue: "right_command", language: .russian),
            "\u{2318} справа"
        )
    }

    func testStalePermissionHintIsLocalized() {
        let russian = DictationSettingsCopy.stalePermissionHint(language: .russian)
        let english = DictationSettingsCopy.stalePermissionHint(language: .english)

        XCTAssertTrue(russian.contains("перезапусти приложение"))
        XCTAssertTrue(russian.contains("удали старые строки"))
        XCTAssertFalse(russian.contains("System Settings"))
        XCTAssertTrue(english.contains("System Settings"))
        XCTAssertTrue(english.contains("remove old rows"))
    }
}
