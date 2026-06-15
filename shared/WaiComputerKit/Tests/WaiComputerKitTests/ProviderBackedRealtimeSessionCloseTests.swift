import XCTest

final class ProviderBackedRealtimeSessionCloseTests: XCTestCase {
    func testProviderBackedCloseDoesNotSwallowEndTurnFailures() throws {
        let source = try sharedSource("Sources/WaiComputerKit/Network/ProviderBackedRealtimeSession.swift")

        XCTAssertTrue(source.contains("try await endTurn()"))
        XCTAssertFalse(source.contains("try? await endTurn()"))
    }

    private func sharedSource(_ relativePath: String) throws -> String {
        try String(contentsOf: try sharedURL(relativePath), encoding: .utf8)
    }

    private func sharedURL(_ relativePath: String) throws -> URL {
        try sharedRoot().appendingPathComponent(relativePath)
    }

    private func sharedRoot() throws -> URL {
        let candidates = [
            URL(fileURLWithPath: #filePath),
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath),
        ]

        for candidate in candidates {
            var directory = candidate.hasDirectoryPath ? candidate : candidate.deletingLastPathComponent()
            while directory.path != directory.deletingLastPathComponent().path {
                let marker = directory.appendingPathComponent("Package.swift")
                let sources = directory.appendingPathComponent("Sources/WaiComputerKit")
                if FileManager.default.fileExists(atPath: marker.path),
                   FileManager.default.fileExists(atPath: sources.path) {
                    return directory
                }
                directory.deleteLastPathComponent()
            }
        }

        throw XCTSkip("Unable to locate WaiComputerKit package root from test runtime")
    }
}
