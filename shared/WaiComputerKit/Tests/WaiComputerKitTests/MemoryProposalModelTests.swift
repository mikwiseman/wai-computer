import Foundation
import XCTest
@testable import WaiComputerKit

final class MemoryProposalModelTests: XCTestCase {
    private func decoder() -> JSONDecoder { JSONDecoder() }

    func testProposalListDecodesWithSnakeCaseKeys() throws {
        let json = """
        {
          "proposals": [
            {
              "id": "p1",
              "kind": "memory_upsert",
              "risk": "high",
              "block_label": "human",
              "operation": "rewrite",
              "content": "Curated bio.",
              "target_line": null,
              "summary": "rewrite → human: Curated bio.",
              "confidence": 0.95,
              "authority": "self",
              "evidence": [{"source_kind": "recording", "title": "Launch sync"}],
              "status": "pending",
              "decision_reason": null,
              "created_at": "2026-06-01T13:00:00Z",
              "decided_at": null
            }
          ],
          "pending_count": 1
        }
        """.data(using: .utf8)!

        let list = try decoder().decode(MemoryProposalList.self, from: json)
        XCTAssertEqual(list.pendingCount, 1)
        XCTAssertEqual(list.proposals.count, 1)
        let p = list.proposals[0]
        XCTAssertEqual(p.id, "p1")
        XCTAssertEqual(p.blockLabel, "human")
        XCTAssertEqual(p.operation, "rewrite")
        XCTAssertEqual(p.content, "Curated bio.")
        XCTAssertNil(p.targetLine)
        XCTAssertEqual(p.confidence, 0.95, accuracy: 0.0001)
        XCTAssertEqual(p.authority, "self")
        XCTAssertEqual(p.evidence?.first?.objectValue?["title"]?.stringValue, "Launch sync")
        XCTAssertNil(p.decisionReason)
        XCTAssertEqual(p.createdAt, "2026-06-01T13:00:00Z")
        XCTAssertNil(p.decidedAt)
        XCTAssertTrue(p.isPending)
        XCTAssertTrue(p.isHighRisk)
    }

    func testAcceptedAdditiveProposalDecodes() throws {
        let json = """
        {
          "id": "p2",
          "kind": "memory_upsert",
          "risk": "low",
          "block_label": "topics",
          "operation": "append",
          "content": "v0.2.0 in progress",
          "target_line": null,
          "summary": "append → topics: v0.2.0 in progress",
          "confidence": 0.9,
          "authority": "self",
          "evidence": null,
          "status": "accepted",
          "decision_reason": "auto: low-risk, confidence 0.90 >= 0.8",
          "created_at": "2026-06-01T13:00:00Z",
          "decided_at": "2026-06-01T13:00:01Z"
        }
        """.data(using: .utf8)!

        let p = try decoder().decode(MemoryProposal.self, from: json)
        XCTAssertEqual(p.blockLabel, "topics")
        XCTAssertEqual(p.status, "accepted")
        XCTAssertFalse(p.isPending)
        XCTAssertFalse(p.isHighRisk)
        XCTAssertEqual(p.decidedAt, "2026-06-01T13:00:01Z")
        XCTAssertNotNil(p.decisionReason)
    }

    func testRejectRequestEncodesReason() throws {
        let body = RejectProposalRequest(reason: "not relevant")
        let data = try JSONEncoder().encode(body)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(obj?["reason"] as? String, "not relevant")
    }
}
