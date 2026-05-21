import XCTest
@testable import WaiComputerKit

final class RealtimeAudioStartupBufferTests: XCTestCase {
    func testBuffersPCMBeforeConnectAndFlushesInOrder() async throws {
        let buffer = RealtimeAudioStartupBuffer(maxBufferedBytes: 10)
        let sent = SentPCM()

        try await buffer.append(Data([0x01, 0x02])) { data in
            await sent.append(data)
        }
        try await buffer.append(Data([0x03])) { data in
            await sent.append(data)
        }

        var values = await sent.values()
        var bufferedBytes = await buffer.bufferedBytes
        XCTAssertEqual(values, [])
        XCTAssertEqual(bufferedBytes, 3)

        try await buffer.connectAndFlush { data in
            await sent.append(data)
        }

        values = await sent.values()
        bufferedBytes = await buffer.bufferedBytes
        XCTAssertEqual(values, [Data([0x01, 0x02]), Data([0x03])])
        XCTAssertEqual(bufferedBytes, 0)

        try await buffer.append(Data([0x04])) { data in
            await sent.append(data)
        }

        values = await sent.values()
        XCTAssertEqual(values, [Data([0x01, 0x02]), Data([0x03]), Data([0x04])])
    }

    func testStartupBufferEvictsOldestPCMWhenCapacityIsExceeded() async throws {
        let buffer = RealtimeAudioStartupBuffer(maxBufferedBytes: 4)
        let sent = SentPCM()

        try await buffer.append(Data([0x01, 0x01])) { data in
            await sent.append(data)
        }
        try await buffer.append(Data([0x02, 0x02])) { data in
            await sent.append(data)
        }
        try await buffer.append(Data([0x03, 0x03])) { data in
            await sent.append(data)
        }

        try await buffer.connectAndFlush { data in
            await sent.append(data)
        }

        let values = await sent.values()
        XCTAssertEqual(values, [Data([0x02, 0x02]), Data([0x03, 0x03])])
    }

    func testFailedFlushKeepsBufferedPCMForRetry() async throws {
        let buffer = RealtimeAudioStartupBuffer(maxBufferedBytes: 10)
        let sent = SentPCM()

        try await buffer.append(Data([0x01, 0x02])) { data in
            await sent.append(data)
        }
        try await buffer.append(Data([0x03])) { data in
            await sent.append(data)
        }

        do {
            try await buffer.connectAndFlush { _ in
                throw TestFlushError.failedSend
            }
            XCTFail("Expected first flush to fail")
        } catch TestFlushError.failedSend {
        }

        let bufferedBytesAfterFailure = await buffer.bufferedBytes
        XCTAssertEqual(bufferedBytesAfterFailure, 3)

        try await buffer.connectAndFlush { data in
            await sent.append(data)
        }

        let values = await sent.values()
        XCTAssertEqual(values, [Data([0x01, 0x02]), Data([0x03])])
        let bufferedBytesAfterRetry = await buffer.bufferedBytes
        XCTAssertEqual(bufferedBytesAfterRetry, 0)
    }
}

private actor SentPCM {
    private var chunks: [Data] = []

    func append(_ data: Data) {
        chunks.append(data)
    }

    func values() -> [Data] {
        chunks
    }
}

private enum TestFlushError: Error {
    case failedSend
}
