import Foundation
import XCTest
@testable import WaiComputerKit

final class InboxModelTests: XCTestCase {
    private func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)

            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: dateString) {
                return date
            }

            formatter.formatOptions = [.withInternetDateTime]
            if let date = formatter.date(from: dateString) {
                return date
            }

            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode date: \(dateString)"
            )
        }
        return decoder
    }

    func testInboxResponseDecodesMixedRows() throws {
        let json = """
        {
          "rows": [
            {
              "id": "recording:r1",
              "source_kind": "recording",
              "source_id": "r1",
              "detail": {"kind": "recording", "id": "r1"},
              "title": "Product sync",
              "source_label": "Recording",
              "sublabel": "meeting",
              "activity_at": "2026-06-03T10:00:00Z",
              "created_at": "2026-06-03T10:00:00Z",
              "updated_at": "2026-06-03T10:01:00Z",
              "occurred_at": null,
              "status": "ready",
              "source_status": "ready",
              "error": null,
              "folder_id": "f1",
              "duration_seconds": 180,
              "language": "en",
              "has_summary": true,
              "is_starred": true,
              "is_pinned": false,
              "is_archived": false,
              "is_trashed": false
            },
            {
              "id": "item:i1",
              "source_kind": "item",
              "source_id": "i1",
              "detail": {"kind": "item", "id": "i1"},
              "title": "Market memo",
              "source_label": "Material",
              "sublabel": "pdf",
              "activity_at": "2026-06-03T09:00:00Z",
              "created_at": "2026-06-03T09:00:00Z",
              "updated_at": "2026-06-03T09:00:00Z",
              "occurred_at": null,
              "status": "needs_input",
              "source_status": "needs_input",
              "error": {"code": "source_needs_login", "message": "Paste text"},
              "folder_id": null,
              "duration_seconds": null,
              "language": null,
              "has_summary": false,
              "is_starred": false,
              "is_pinned": false,
              "is_archived": false,
              "is_trashed": false
            },
            {
              "id": "chat:c1",
              "source_kind": "chat",
              "source_id": "c1",
              "detail": {"kind": "chat", "id": "c1"},
              "title": null,
              "source_label": "Wai chat",
              "sublabel": "Chat",
              "activity_at": "2026-06-03T08:00:00Z",
              "created_at": "2026-06-03T08:00:00Z",
              "updated_at": "2026-06-03T08:00:00Z",
              "occurred_at": null,
              "status": "ready",
              "source_status": null,
              "error": null,
              "folder_id": null,
              "duration_seconds": null,
              "language": null,
              "has_summary": null,
              "is_starred": false,
              "is_pinned": true,
              "is_archived": false,
              "is_trashed": false
            }
          ],
          "next_cursor": "abc",
          "has_more": true
        }
        """.data(using: .utf8)!

        let response = try makeDecoder().decode(InboxResponse.self, from: json)
        XCTAssertEqual(response.rows.count, 3)
        XCTAssertEqual(response.rows[0].sourceKind, .recording)
        XCTAssertEqual(response.rows[0].status, .ready)
        XCTAssertEqual(response.rows[0].folderId, "f1")
        XCTAssertEqual(response.rows[1].status, .needsInput)
        XCTAssertEqual(response.rows[1].error?.code, "source_needs_login")
        XCTAssertEqual(response.rows[2].sourceKind, .chat)
        XCTAssertTrue(response.rows[2].isPinned)
        XCTAssertEqual(response.nextCursor, "abc")
        XCTAssertTrue(response.hasMore)
    }
}
