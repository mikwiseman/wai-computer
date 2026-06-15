import XCTest

final class ProviderBackedRealtimeSessionCloseTests: XCTestCase {
    func testProviderBackedCloseDoesNotSwallowEndTurnFailures() throws {
        let source = try sharedSource("Sources/WaiComputerKit/Network/ProviderBackedRealtimeSession.swift")

        XCTAssertTrue(source.contains("try await endTurn()"))
        XCTAssertFalse(source.contains("try? await endTurn()"))
    }

    func testDictationSessionCommitDoesNotSwallowProviderFinalizationFailures() throws {
        let source = try sharedSource("Sources/WaiComputerKit/Network/DictationSession.swift")
        let commit = try functionBody(
            named: "public func commit(timeout: Duration = .seconds(3))",
            in: source,
            endingBefore: "/// Cancel without producing a transcript."
        )

        XCTAssertTrue(commit.contains("async throws -> Outcome"))
        XCTAssertTrue(commit.contains("try await provider.endTurn()"))
        XCTAssertTrue(commit.contains("try await provider.close(timeout: timeout)"))
        XCTAssertTrue(commit.contains("provider.finalize: \\(error.localizedDescription)"))
        XCTAssertFalse(commit.contains("try? await provider.endTurn()"))
        XCTAssertFalse(commit.contains("(try? await provider.close(timeout: timeout)) ?? []"))
    }

    private func sharedSource(_ relativePath: String) throws -> String {
        try String(contentsOf: try sharedURL(relativePath), encoding: .utf8)
    }

    private func functionBody(
        named declaration: String,
        in source: String,
        endingBefore terminator: String
    ) throws -> String {
        guard let start = source.range(of: declaration)?.lowerBound,
              let end = source[start...].range(of: terminator)?.lowerBound else {
            throw XCTSkip("Unable to locate \(declaration)")
        }
        return String(source[start..<end])
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
