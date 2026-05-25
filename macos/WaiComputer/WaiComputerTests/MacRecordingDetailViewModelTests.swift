import XCTest
import WaiComputerKit

@MainActor
final class MacRecordingDetailViewModelTests: XCTestCase {
    override func tearDown() {
        MacRecordingDetailMockURLProtocol.requestHandler = nil
        super.tearDown()
    }

    func testFailedLoadForNewRecordingClearsPreviousDetail() async {
        let previousDetail = makeDetail(id: "previous-recording", title: "Previous Recording")
        let viewModel = MacRecordingDetailViewModel(initialDetail: previousDetail)
        let apiClient = makeAPIClient(statusCode: 500, body: #"{"detail":"Latest recording is not ready"}"#)

        await viewModel.load(recordingId: "latest-recording", apiClient: apiClient)

        XCTAssertNil(viewModel.recordingDetail)
        XCTAssertNotNil(viewModel.error)
        XCTAssertFalse(viewModel.isLoading)
    }

    func testFailedRefreshForCurrentRecordingKeepsDetailAndSurfacesError() async {
        let currentDetail = makeDetail(id: "current-recording", title: "Current Recording")
        let viewModel = MacRecordingDetailViewModel(initialDetail: currentDetail)
        let apiClient = makeAPIClient(statusCode: 503, body: #"{"detail":"Temporary outage"}"#)

        await viewModel.load(recordingId: "current-recording", apiClient: apiClient, showLoading: false)

        XCTAssertEqual(viewModel.recordingDetail?.id, currentDetail.id)
        XCTAssertNotNil(viewModel.error)
        XCTAssertFalse(viewModel.isLoading)
    }

    private func makeDetail(id: String, title: String) -> RecordingDetail {
        RecordingDetail(
            id: id,
            title: title,
            type: .meeting,
            status: .ready,
            durationSeconds: 60,
            language: "en",
            createdAt: Date(timeIntervalSince1970: 1_709_292_000),
            segments: []
        )
    }

    private func makeAPIClient(statusCode: Int, body: String) -> APIClient {
        MacRecordingDetailMockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: statusCode,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MacRecordingDetailMockURLProtocol.self]
        let session = URLSession(configuration: configuration)
        return APIClient(baseURL: URL(string: "https://example.test")!, session: session)
    }
}

private final class MacRecordingDetailMockURLProtocol: URLProtocol, @unchecked Sendable {
    static var requestHandler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let requestHandler = Self.requestHandler else {
            XCTFail("MacRecordingDetailMockURLProtocol.requestHandler is not set")
            client?.urlProtocol(self, didFailWithError: APIError.noData)
            return
        }

        do {
            let (response, data) = try requestHandler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
