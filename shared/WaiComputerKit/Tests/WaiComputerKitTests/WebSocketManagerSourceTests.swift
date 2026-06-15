import XCTest

final class WebSocketManagerSourceTests: XCTestCase {
    func testRecordingWebSocketManagerWaitsForHandshakeOnConnectAndReconnect() throws {
        let source = try repoSource(
            "shared/WaiComputerKit/Sources/WaiComputerKit/Network/WebSocketManager.swift"
        )
        let connect = try functionBody(
            named: "public func connect(",
            in: source,
            endingBefore: "/// Send raw PCM audio data directly to the configured provider."
        )
        let reconnectLoop = try functionBody(
            named: "private func reconnectLoop() async",
            in: source,
            endingBefore: "private func sendCommitChunkIfNeeded() async throws"
        )

        XCTAssertTrue(source.contains("private static let handshakeTimeout: Duration = .seconds(10)"))
        XCTAssertTrue(source.contains("URLSession(configuration: sessionConfig, delegate: coordinator, delegateQueue: nil)"))
        XCTAssertTrue(source.contains("try await Self.awaitHandshake("))
        XCTAssertTrue(connect.contains("try await openRealtimeSocket("))
        XCTAssertTrue(reconnectLoop.contains("try await openRealtimeSocket("))
        XCTAssertFalse(connect.contains("let session = URLSession(configuration: .default)"))
        XCTAssertFalse(reconnectLoop.contains("let session = URLSession(configuration: .default)"))
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

    private func repoSource(_ relativePath: String) throws -> String {
        try String(contentsOf: try repoRoot().appendingPathComponent(relativePath), encoding: .utf8)
    }

    private func repoRoot() throws -> URL {
        let candidates = [
            URL(fileURLWithPath: #filePath),
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath),
        ]

        for candidate in candidates {
            var directory = candidate.hasDirectoryPath ? candidate : candidate.deletingLastPathComponent()
            while directory.path != directory.deletingLastPathComponent().path {
                let marker = directory.appendingPathComponent("scripts/macos-peekaboo-smoke.sh")
                if FileManager.default.fileExists(atPath: marker.path) {
                    return directory
                }
                directory.deleteLastPathComponent()
            }
        }

        throw XCTSkip("Unable to locate wai-computer repo root from test runtime")
    }
}
