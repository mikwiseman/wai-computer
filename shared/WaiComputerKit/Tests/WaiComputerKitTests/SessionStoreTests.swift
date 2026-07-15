import XCTest
@testable import WaiComputerKit

final class SessionStoreTests: XCTestCase {
    private var tempBase: URL!
    private var fileManager: FileManager!
    private var store: SessionStore!

    override func setUpWithError() throws {
        fileManager = FileManager()
        tempBase = fileManager.temporaryDirectory
            .appendingPathComponent("SessionStoreTests-\(UUID().uuidString)", isDirectory: true)
        try fileManager.createDirectory(at: tempBase, withIntermediateDirectories: true)
        // The SessionStore writes under the user's Application Support dir.
        // Test isolation: instantiate with a unique sub-directory so writes
        // do not collide with the real app on the dev machine.
        store = SessionStore(fileManager: fileManager, directoryName: "WaiComputerTests-\(UUID().uuidString)")
    }

    override func tearDownWithError() throws {
        store.clear()
        if let tempBase, fileManager.fileExists(atPath: tempBase.path) {
            try? fileManager.removeItem(at: tempBase)
        }
    }

    func testSaveLoadRoundTrip() throws {
        try store.save(accessToken: "access-1", refreshToken: "refresh-1")
        let loaded = store.load()
        XCTAssertEqual(loaded?.accessToken, "access-1")
        XCTAssertEqual(loaded?.refreshToken, "refresh-1")
    }

    func testSaveOverwritesExistingSession() throws {
        try store.save(accessToken: "first", refreshToken: nil)
        try store.save(accessToken: "second", refreshToken: "with-refresh")
        let loaded = store.load()
        XCTAssertEqual(loaded?.accessToken, "second")
        XCTAssertEqual(loaded?.refreshToken, "with-refresh")
    }

    func testClearRemovesFile() throws {
        try store.save(accessToken: "to-be-cleared", refreshToken: nil)
        store.clear()
        XCTAssertNil(store.load())
        XCTAssertFalse(fileManager.fileExists(atPath: store.sessionFileURL.path))
    }

    func testLoadReturnsNilWhenAbsent() {
        XCTAssertNil(store.load())
    }

    func testFileMode0600() throws {
        try store.save(accessToken: "secret", refreshToken: nil)
        let attrs = try fileManager.attributesOfItem(atPath: store.sessionFileURL.path)
        let mode = attrs[.posixPermissions] as? NSNumber
        XCTAssertEqual(mode?.uint16Value, 0o600)
    }

    func testSessionDirEnvOverrideWinsOverApplicationSupport() throws {
        // WAICOMPUTER_SESSION_DIR isolates a second instance (debug/QA build)
        // from the production app's session.json — the shared-file race used
        // to sign both instances out.
        setenv("WAICOMPUTER_SESSION_DIR", tempBase.path, 1)
        defer { unsetenv("WAICOMPUTER_SESSION_DIR") }
        let isolated = SessionStore(fileManager: fileManager, directoryName: "WaiComputerTestOverride")
        XCTAssertEqual(
            isolated.sessionFileURL,
            tempBase.appendingPathComponent("session.json")
        )
    }

}
