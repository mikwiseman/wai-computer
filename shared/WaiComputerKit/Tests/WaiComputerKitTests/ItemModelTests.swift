import Foundation
import XCTest
@testable import WaiComputerKit

/// Decoding tests for the second-brain Item / key-moments / unified-search models.
final class ItemModelTests: XCTestCase {
    private func decoder() -> JSONDecoder { JSONDecoder() }

    func testItemWithSummaryAndKeyMomentsDecodes() throws {
        let json = """
        {
          "id": "i1",
          "source": "url",
          "source_ref": null,
          "url": "https://x/post",
          "kind": "article",
          "title": "Solar Explainer",
          "body": "full text",
          "occurred_at": null,
          "state": "raw",
          "folder_id": null,
          "created_at": "2026-06-01T00:00:00Z",
          "summary": {
            "summary": "A clear explainer.",
            "key_points": ["costs fell", "storage grew"],
            "topics": ["energy"],
            "key_moments": [
              {
                "timestamp": "00:42",
                "moment": "Thesis stated",
                "why_it_matters": "Frames the argument",
                "quote": null,
                "importance": "high",
                "start_ms": 42000,
                "end_ms": 50000
              }
            ],
            "sentiment": "positive"
          }
        }
        """.data(using: .utf8)!

        let item = try decoder().decode(Item.self, from: json)
        XCTAssertEqual(item.id, "i1")
        XCTAssertEqual(item.kind, "article")
        XCTAssertEqual(item.title, "Solar Explainer")
        XCTAssertEqual(item.summary?.summary, "A clear explainer.")
        XCTAssertEqual(item.summary?.keyPoints, ["costs fell", "storage grew"])
        let moment = try XCTUnwrap(item.summary?.keyMoments?.first)
        XCTAssertEqual(moment.timestamp, "00:42")
        XCTAssertEqual(moment.moment, "Thesis stated")
        XCTAssertEqual(moment.whyItMatters, "Frames the argument")
        XCTAssertEqual(moment.startMs, 42000)
    }

    func testItemWithoutSummaryDecodes() throws {
        let json = """
        {
          "id": "i2", "source": "paste", "source_ref": null, "url": null,
          "kind": "note", "title": null, "body": "x", "occurred_at": null,
          "state": "raw", "folder_id": null, "created_at": "2026-06-01T00:00:00Z",
          "summary": null
        }
        """.data(using: .utf8)!
        let item = try decoder().decode(Item.self, from: json)
        XCTAssertNil(item.summary)
        XCTAssertNil(item.title)
    }

    func testItemListResponseDecodes() throws {
        let json = """
        {
          "items": [
            {
              "id": "i1", "source": "url", "url": "https://x", "kind": "article",
              "title": "T", "state": "raw", "folder_id": null, "occurred_at": null,
              "created_at": "2026-06-01T00:00:00Z", "has_summary": true
            }
          ],
          "total": 1
        }
        """.data(using: .utf8)!
        let response = try decoder().decode(ItemListResponse.self, from: json)
        XCTAssertEqual(response.total, 1)
        XCTAssertTrue(response.items[0].hasSummary)
    }

    func testUnifiedSearchResponseDecodes() throws {
        let json = """
        {
          "results": [
            {
              "source_kind": "item", "parent_id": "p1", "chunk_id": "c1",
              "title": "T", "kind": "article", "snippet": "snip", "score": 0.9,
              "created_at": "2026-06-01T00:00:00Z"
            },
            {
              "source_kind": "recording", "parent_id": "r1", "chunk_id": "seg1",
              "title": null, "kind": "meeting", "snippet": "s2", "score": 0.5,
              "created_at": null
            }
          ],
          "total": 2
        }
        """.data(using: .utf8)!
        let response = try decoder().decode(UnifiedSearchResponse.self, from: json)
        XCTAssertEqual(response.total, 2)
        XCTAssertEqual(response.results[0].sourceKind, "item")
        XCTAssertEqual(response.results[0].parentId, "p1")
        XCTAssertEqual(response.results[1].sourceKind, "recording")
        XCTAssertNil(response.results[1].createdAt)
    }
}
