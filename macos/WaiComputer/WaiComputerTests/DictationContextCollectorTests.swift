import XCTest

@MainActor
final class DictationContextCollectorTests: XCTestCase {
    func testAppCategoryClassifiesCommonDictationTargets() {
        XCTAssertEqual(
            DictationContextCollector.appCategory(
                bundleID: "com.todesktop.230313mzl4w4u92",
                name: "Cursor"
            ),
            "engineering"
        )
        XCTAssertEqual(
            DictationContextCollector.appCategory(
                bundleID: "com.apple.mail",
                name: "Mail"
            ),
            "email"
        )
        XCTAssertEqual(
            DictationContextCollector.appCategory(
                bundleID: "com.linear",
                name: "Linear"
            ),
            "project_management"
        )
        XCTAssertEqual(
            DictationContextCollector.appCategory(
                bundleID: "company.thebrowser.Browser",
                name: "Arc"
            ),
            "browser"
        )
    }
}
