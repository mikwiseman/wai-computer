import XCTest

extension XCUIApplication {
    func configureWaiComputerUITestLaunch(
        scenario: String? = nil,
        skipOnboarding: Bool = false,
        forceOnboarding: Bool = false,
        permissionMock: String? = nil,
        disableStoredSessionRestore: Bool = true,
        launchArguments additionalLaunchArguments: [String] = []
    ) {
        launchEnvironment["WAI_ENABLE_UI_TEST_MODE"] = "1"
        if let scenario {
            launchEnvironment["UITEST_SCENARIO"] = scenario
        }
        if skipOnboarding {
            launchEnvironment["WAI_SKIP_ONBOARDING"] = "1"
        }
        if forceOnboarding {
            launchEnvironment["WAI_FORCE_ONBOARDING"] = "1"
        }
        if let permissionMock {
            launchEnvironment["WAI_MOCK_DICTATION_PERMISSIONS"] = permissionMock
        }
        if disableStoredSessionRestore {
            launchEnvironment["WAI_DISABLE_STORED_SESSION_RESTORE"] = "1"
        }
        let languageArguments = additionalLaunchArguments.contains("-waiUserLanguage")
            ? []
            : ["-waiUserLanguage", "en"]

        launchArguments = [
            "-ApplePersistenceIgnoreState", "YES",
        ] + languageArguments + additionalLaunchArguments
    }
}
