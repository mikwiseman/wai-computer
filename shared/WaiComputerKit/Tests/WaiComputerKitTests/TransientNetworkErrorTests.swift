import XCTest
@testable import WaiComputerKit

final class TransientNetworkErrorTests: XCTestCase {
    func testSettlingNetworkFailuresAreTransient() {
        let transientCodes: [URLError.Code] = [
            .notConnectedToInternet,
            .networkConnectionLost,
            .timedOut,
            .cannotConnectToHost,
            .cannotFindHost,
            .dnsLookupFailed,
        ]
        for code in transientCodes {
            XCTAssertTrue(URLError(code).isTransientNetworkError, "\(code) should be transient")
            XCTAssertTrue(
                APIError.networkError(URLError(code)).isTransientNetworkError,
                "APIError-wrapped \(code) should be transient"
            )
        }
    }

    func testRealFailuresStayLoud() {
        XCTAssertFalse(URLError(.badServerResponse).isTransientNetworkError)
        XCTAssertFalse(URLError(.cancelled).isTransientNetworkError)
        XCTAssertFalse(APIError.unauthorized.isTransientNetworkError)
        XCTAssertFalse(
            APIError.httpError(statusCode: 500, message: nil).isTransientNetworkError
        )
        XCTAssertFalse(APIError.decodingError(URLError(.timedOut)).isTransientNetworkError)
    }
}
