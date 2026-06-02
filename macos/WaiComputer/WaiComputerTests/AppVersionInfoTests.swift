import XCTest

final class AppVersionInfoTests: XCTestCase {
    func testDisplayTextCombinesMarketingVersionAndBuildNumber() throws {
        let info = try AppVersionInfo(
            infoDictionary: [
                "CFBundleShortVersionString": "1.0.26",
                "CFBundleVersion": "166"
            ]
        )

        XCTAssertEqual(info.displayText, "1.0.26 (166)")
    }

    func testMissingMarketingVersionThrows() {
        XCTAssertThrowsError(
            try AppVersionInfo(infoDictionary: ["CFBundleVersion": "166"])
        ) { error in
            XCTAssertEqual(error as? AppVersionInfo.Error, .missingMarketingVersion)
        }
    }

    func testMissingInfoDictionaryThrows() {
        XCTAssertThrowsError(
            try AppVersionInfo(infoDictionary: nil)
        ) { error in
            XCTAssertEqual(error as? AppVersionInfo.Error, .missingInfoDictionary)
        }
    }

    func testMissingBuildNumberThrows() {
        XCTAssertThrowsError(
            try AppVersionInfo(infoDictionary: ["CFBundleShortVersionString": "1.0.26"])
        ) { error in
            XCTAssertEqual(error as? AppVersionInfo.Error, .missingBuildNumber)
        }
    }
}
