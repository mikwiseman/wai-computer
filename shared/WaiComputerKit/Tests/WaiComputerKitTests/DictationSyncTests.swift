import Foundation
import XCTest
@testable import WaiComputerKit

final class DictationSyncTests: XCTestCase {
    override func setUp() {
        super.setUp()
        MockURLProtocol.requestHandler = nil
    }

    private func makeClient(baseURL: URL = URL(string: "https://api.example.com")!) -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        return APIClient(baseURL: baseURL, session: session)
    }

    private func bodyData(from request: URLRequest) -> Data? {
        if let data = request.httpBody { return data }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var data = Data()
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4096)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let bytesRead = stream.read(buffer, maxLength: 4096)
            if bytesRead <= 0 { break }
            data.append(buffer, count: bytesRead)
        }
        return data
    }

    // MARK: - createDictationEntry

    func testCreateDictationEntryPostsSnakeCaseBody() async throws {
        let client = makeClient()
        let clientEntryID = UUID()
        let captured = NSLock()
        nonisolated(unsafe) var capturedBody: [String: Any]?
        nonisolated(unsafe) var capturedMethod: String?
        nonisolated(unsafe) var capturedPath: String?

        MockURLProtocol.requestHandler = { [self] request in
            captured.withLock {
                capturedMethod = request.httpMethod
                capturedPath = request.url?.path
                if let data = bodyData(from: request) {
                    capturedBody = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                }
            }
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 201, httpVersion: nil, headerFields: nil
            )!
            let payload: [String: Any] = [
                "client_entry_id": clientEntryID.uuidString.lowercased(),
                "raw_text": "hello",
                "cleaned_text": "Hello.",
                "duration_seconds": 1.5,
                "word_count": 1,
                "occurred_at": "2026-05-18T12:00:00Z",
            ]
            let data = try JSONSerialization.data(withJSONObject: payload)
            return (response, data)
        }

        let request = CreateDictationEntryRequest(
            clientEntryID: clientEntryID,
            rawText: "hello",
            cleanedText: "Hello.",
            durationSeconds: 1.5,
            wordCount: 1,
            occurredAt: "2026-05-18T12:00:00Z"
        )
        let dto = try await client.createDictationEntry(request)

        XCTAssertEqual(capturedMethod, "POST")
        XCTAssertEqual(capturedPath, "/api/dictation/entries")
        let body = try XCTUnwrap(capturedBody)
        // Swift's default UUID encoding is uppercase; backend accepts either.
        XCTAssertEqual(
            (body["client_entry_id"] as? String)?.lowercased(),
            clientEntryID.uuidString.lowercased()
        )
        XCTAssertEqual(body["raw_text"] as? String, "hello")
        XCTAssertEqual(body["cleaned_text"] as? String, "Hello.")
        XCTAssertEqual(body["duration_seconds"] as? Double, 1.5)
        XCTAssertEqual(body["word_count"] as? Int, 1)
        XCTAssertEqual(body["occurred_at"] as? String, "2026-05-18T12:00:00Z")

        XCTAssertEqual(dto.clientEntryID, clientEntryID)
        XCTAssertEqual(dto.rawText, "hello")
        XCTAssertEqual(dto.cleanedText, "Hello.")
    }

    // MARK: - listDictationEntries

    func testListDictationEntriesDecodesSnakeCase() async throws {
        let client = makeClient()
        let entryID = UUID()
        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/dictation/entries")
            let payload: [[String: Any]] = [[
                "client_entry_id": entryID.uuidString,
                "raw_text": "первое сообщение",
                "cleaned_text": NSNull(),
                "duration_seconds": 2.0,
                "word_count": 2,
                "occurred_at": "2026-05-18T08:00:00Z",
            ]]
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
            )!
            let data = try JSONSerialization.data(withJSONObject: payload)
            return (response, data)
        }

        let entries = try await client.listDictationEntries()
        XCTAssertEqual(entries.count, 1)
        XCTAssertEqual(entries[0].clientEntryID, entryID)
        XCTAssertEqual(entries[0].rawText, "первое сообщение")
        XCTAssertNil(entries[0].cleanedText)
        XCTAssertEqual(entries[0].wordCount, 2)
    }

    // MARK: - deleteDictationEntry

    func testDeleteDictationEntryUsesLowercaseUUIDInPath() async throws {
        let client = makeClient()
        let entryID = UUID()
        let captured = NSLock()
        nonisolated(unsafe) var capturedPath: String?
        nonisolated(unsafe) var capturedMethod: String?

        MockURLProtocol.requestHandler = { request in
            captured.withLock {
                capturedPath = request.url?.path
                capturedMethod = request.httpMethod
            }
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 204, httpVersion: nil, headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteDictationEntry(clientEntryID: entryID)
        XCTAssertEqual(capturedMethod, "DELETE")
        XCTAssertEqual(
            capturedPath,
            "/api/dictation/entries/\(entryID.uuidString.lowercased())"
        )
    }

    // MARK: - dictionary endpoints

    func testCreateDictionaryWordPostsSnakeCaseBody() async throws {
        let client = makeClient()
        let wordID = UUID()
        let captured = NSLock()
        nonisolated(unsafe) var capturedBody: [String: Any]?

        MockURLProtocol.requestHandler = { [self] request in
            captured.withLock {
                if let data = bodyData(from: request) {
                    capturedBody = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                }
            }
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 201, httpVersion: nil, headerFields: nil
            )!
            let payload: [String: Any] = [
                "client_word_id": wordID.uuidString.lowercased(),
                "word": "kubernetes",
                "replacement": "k8s",
                "occurred_at": "2026-05-18T12:00:00Z",
            ]
            let data = try JSONSerialization.data(withJSONObject: payload)
            return (response, data)
        }

        let request = CreateDictionaryWordRequest(
            clientWordID: wordID,
            word: "kubernetes",
            replacement: "k8s",
            occurredAt: "2026-05-18T12:00:00Z"
        )
        _ = try await client.createDictionaryWord(request)
        let body = try XCTUnwrap(capturedBody)
        XCTAssertEqual(
            (body["client_word_id"] as? String)?.lowercased(),
            wordID.uuidString.lowercased()
        )
        XCTAssertEqual(body["word"] as? String, "kubernetes")
        XCTAssertEqual(body["replacement"] as? String, "k8s")
    }

    func testListDictionaryWordsDecodesNullReplacement() async throws {
        let client = makeClient()
        let wordID = UUID()
        MockURLProtocol.requestHandler = { request in
            let payload: [[String: Any]] = [[
                "client_word_id": wordID.uuidString,
                "word": "latency",
                "replacement": NSNull(),
                "occurred_at": "2026-05-18T08:00:00Z",
            ]]
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
            )!
            return (response, try JSONSerialization.data(withJSONObject: payload))
        }

        let words = try await client.listDictationDictionary()
        XCTAssertEqual(words.count, 1)
        XCTAssertEqual(words[0].clientWordID, wordID)
        XCTAssertEqual(words[0].word, "latency")
        XCTAssertNil(words[0].replacement)
    }

    func testDeleteDictionaryWordHitsExpectedPath() async throws {
        let client = makeClient()
        let wordID = UUID()
        let captured = NSLock()
        nonisolated(unsafe) var capturedPath: String?

        MockURLProtocol.requestHandler = { request in
            captured.withLock { capturedPath = request.url?.path }
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 204, httpVersion: nil, headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteDictionaryWord(clientWordID: wordID)
        XCTAssertEqual(
            capturedPath,
            "/api/dictation/dictionary/\(wordID.uuidString.lowercased())"
        )
    }
}
