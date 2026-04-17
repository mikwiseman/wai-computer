/**
 * Type-sync tests: verify that frontend TypeScript types match the structure
 * returned by backend API responses. These tests create mock objects that
 * conform to each type and assert structural correctness — catching drift
 * between frontend types and backend response schemas.
 */
import { describe, expect, it } from "vitest";
import type {
  AnalyticsResponse,
  BulkOperationResponse,
  DailyBreakdown,
  DigestActionItem,
  DigestHighlight,
  Entity,
  EntityDetail,
  Highlight,
  HighlightCategory,
  HighlightImportance,
  Recording,
  RecordingDetail,
  RelatedRecording,
  RelatedRecordingsResponse,
  SearchResponse,
  SearchResult,
  SpeakerStat,
  SpeakerStatsResponse,
  SpeakerTimelineEntry,
  TranscriptSearchMatch,
  TranscriptSearchResponse,
  TranscriptStatsResponse,
  WeeklyDigestResponse,
} from "./types";

/**
 * Helper: assert that an object has exactly the expected keys (no extra, no missing).
 */
function expectExactKeys(obj: Record<string, unknown>, expectedKeys: string[]) {
  const actualKeys = Object.keys(obj).sort();
  const sorted = [...expectedKeys].sort();
  expect(actualKeys).toEqual(sorted);
}

describe("types-sync: Recording", () => {
  it("Recording has all backend-returned fields including starred_at", () => {
    const recording: Recording = {
      id: "r1",
      title: "Sprint Planning",
      type: "meeting",
      audio_url: "https://example.com/audio.webm",
      status: "ready",
      failure_code: null,
      failure_message: null,
      uploaded_at: "2026-03-01T00:00:00Z",
      duration_seconds: 600,
      language: "en",
      folder_id: null,
      deleted_at: null,
      starred_at: "2026-03-10T12:00:00Z",
      created_at: "2026-03-01T00:00:00Z",
    };

    expectExactKeys(recording, [
      "id",
      "title",
      "type",
      "audio_url",
      "status",
      "failure_code",
      "failure_message",
      "uploaded_at",
      "duration_seconds",
      "language",
      "folder_id",
      "deleted_at",
      "starred_at",
      "created_at",
    ]);

    // starred_at is nullable — verify both states
    expect(recording.starred_at).toBe("2026-03-10T12:00:00Z");
    const unstarred: Recording = { ...recording, starred_at: null };
    expect(unstarred.starred_at).toBeNull();
  });

  it("Recording allows nullable fields to be null", () => {
    const recording: Recording = {
      id: "r2",
      title: null,
      type: "note",
      audio_url: null,
      status: "pending_upload",
      failure_code: null,
      failure_message: null,
      uploaded_at: null,
      duration_seconds: null,
      language: null,
      folder_id: null,
      deleted_at: null,
      starred_at: null,
      created_at: "2026-03-01T00:00:00Z",
    };

    expect(recording.title).toBeNull();
    expect(recording.audio_url).toBeNull();
    expect(recording.uploaded_at).toBeNull();
    expect(recording.duration_seconds).toBeNull();
    expect(recording.language).toBeNull();
    expect(recording.folder_id).toBeNull();
    expect(recording.deleted_at).toBeNull();
    expect(recording.starred_at).toBeNull();
  });
});

describe("types-sync: RecordingDetail extends Recording with highlights", () => {
  it("RecordingDetail includes segments, summary, action_items, and highlights", () => {
    const detail: RecordingDetail = {
      id: "r1",
      title: "Planning",
      type: "meeting",
      audio_url: null,
      status: "ready",
      failure_code: null,
      failure_message: null,
      uploaded_at: null,
      duration_seconds: 300,
      language: "en",
      folder_id: null,
      deleted_at: null,
      starred_at: null,
      created_at: "2026-03-01T00:00:00Z",
      segments: [
        { id: "seg1", speaker: "Alice", content: "Hello", start_ms: 0, end_ms: 1000, confidence: 0.95 },
      ],
      summary: {
        summary: "Quick sync",
        key_points: ["Point 1"],
        decisions: [{ decision: "Go ahead" }],
        topics: ["roadmap"],
        people_mentioned: ["Alice"],
        sentiment: "positive",
      },
      action_items: [
        {
          id: "a1",
          recording_id: "r1",
          task: "Follow up",
          owner: "Alice",
          due_date: "2026-03-15",
          priority: "high",
          status: "pending",
          source: "generated",
          created_at: "2026-03-01T00:00:00Z",
        },
      ],
      highlights: [
        {
          id: "h1",
          recording_id: "r1",
          category: "decision",
          title: "Agreed on roadmap",
          description: "Team aligned on Q2 priorities",
          speaker: "Alice",
          start_ms: 5000,
          end_ms: 12000,
          importance: "high",
        },
      ],
    };

    expect(detail.highlights).toHaveLength(1);
    expect(detail.highlights[0].category).toBe("decision");
    expect(detail.highlights[0].importance).toBe("high");
    expect(detail.segments).toHaveLength(1);
    expect(detail.action_items).toHaveLength(1);
    expect(detail.summary).not.toBeNull();
  });

  it("RecordingDetail allows empty highlights array", () => {
    const detail: RecordingDetail = {
      id: "r2",
      title: null,
      type: "note",
      audio_url: null,
      status: "ready",
      failure_code: null,
      failure_message: null,
      uploaded_at: null,
      duration_seconds: null,
      language: null,
      folder_id: null,
      deleted_at: null,
      starred_at: null,
      created_at: "2026-03-01T00:00:00Z",
      segments: [],
      summary: null,
      action_items: [],
      highlights: [],
    };

    expect(detail.highlights).toEqual([]);
    expect(detail.summary).toBeNull();
  });
});

describe("types-sync: Highlight", () => {
  it("Highlight type covers all backend HighlightResponse fields", () => {
    const highlight: Highlight = {
      id: "h1",
      recording_id: "r1",
      category: "insight",
      title: "Key insight about performance",
      description: "Performance improved 30% after refactor",
      speaker: "Bob",
      start_ms: 15000,
      end_ms: 22000,
      importance: "high",
    };

    expectExactKeys(highlight, [
      "id",
      "recording_id",
      "category",
      "title",
      "description",
      "speaker",
      "start_ms",
      "end_ms",
      "importance",
    ]);
  });

  it("HighlightCategory covers all valid backend categories", () => {
    const categories: HighlightCategory[] = [
      "decision",
      "insight",
      "question",
      "concern",
      "topic_shift",
      "quote",
    ];

    // Each category should be assignable to the type
    for (const cat of categories) {
      const h: Highlight = {
        id: "h",
        recording_id: "r",
        category: cat,
        title: "t",
        description: null,
        speaker: null,
        start_ms: null,
        end_ms: null,
        importance: "medium",
      };
      expect(h.category).toBe(cat);
    }
    expect(categories).toHaveLength(6);
  });

  it("HighlightImportance covers all valid backend values", () => {
    const levels: HighlightImportance[] = ["high", "medium", "low"];
    expect(levels).toHaveLength(3);

    for (const level of levels) {
      const h: Highlight = {
        id: "h",
        recording_id: "r",
        category: "decision",
        title: "t",
        description: null,
        speaker: null,
        start_ms: null,
        end_ms: null,
        importance: level,
      };
      expect(h.importance).toBe(level);
    }
  });
});





describe("types-sync: SearchResult and SearchResponse", () => {
  it("SearchResult matches backend response schema", () => {
    const result: SearchResult = {
      recording_id: "r1",
      recording_title: "Planning",
      recording_type: "meeting",
      segment_id: "seg1",
      speaker: "Alice",
      content: "We discussed the roadmap",
      start_ms: 1000,
      end_ms: 5000,
      score: 0.95,
    };

    expectExactKeys(result, [
      "recording_id",
      "recording_title",
      "recording_type",
      "segment_id",
      "speaker",
      "content",
      "start_ms",
      "end_ms",
      "score",
    ]);
  });

  it("SearchResponse wraps results with total count", () => {
    const response: SearchResponse = {
      results: [],
      total: 0,
    };

    expectExactKeys(response, ["results", "total"]);
    expect(response.results).toEqual([]);
    expect(response.total).toBe(0);
  });
});

describe("types-sync: WeeklyDigestResponse", () => {
  it("WeeklyDigestResponse matches backend schema with all nested types", () => {
    const digest: WeeklyDigestResponse = {
      period_start: "2026-03-10",
      period_end: "2026-03-16",
      total_recordings: 12,
      total_duration_seconds: 7200,
      recordings_by_type: { meeting: 8, note: 3, reflection: 1 },
      top_topics: [{ topic: "roadmap", count: 5 }],
      top_people: [{ name: "Alice", count: 4 }],
      pending_action_items: [
        {
          id: "a1",
          recording_id: "r1",
          recording_title: "Sprint Planning",
          task: "Follow up with design team",
          owner: "Bob",
          priority: "high",
          status: "pending",
        },
      ],
      highlights: [
        {
          id: "h1",
          recording_id: "r1",
          recording_title: "Sprint Planning",
          category: "decision",
          title: "Agreed on timeline",
          importance: "high",
        },
      ],
      sentiment_breakdown: { positive: 6, neutral: 4, negative: 2 },
      daily_breakdown: [
        { date: "2026-03-10", count: 3, duration_seconds: 1800 },
      ],
    };

    expectExactKeys(digest, [
      "period_start",
      "period_end",
      "total_recordings",
      "total_duration_seconds",
      "recordings_by_type",
      "top_topics",
      "top_people",
      "pending_action_items",
      "highlights",
      "sentiment_breakdown",
      "daily_breakdown",
    ]);

    // Verify nested type structures
    const actionItem: DigestActionItem = digest.pending_action_items[0];
    expectExactKeys(actionItem, [
      "id",
      "recording_id",
      "recording_title",
      "task",
      "owner",
      "priority",
      "status",
    ]);

    const highlight: DigestHighlight = digest.highlights[0];
    expectExactKeys(highlight, [
      "id",
      "recording_id",
      "recording_title",
      "category",
      "title",
      "importance",
    ]);

    const daily: DailyBreakdown = digest.daily_breakdown[0];
    expectExactKeys(daily, ["date", "count", "duration_seconds"]);
  });
});

describe("types-sync: SpeakerStatsResponse", () => {
  it("SpeakerStatsResponse matches backend schema", () => {
    const stats: SpeakerStatsResponse = {
      recording_id: "r1",
      total_duration_ms: 600000,
      total_speakers: 2,
      speakers: [
        {
          name: "Alice",
          total_duration_ms: 360000,
          percentage: 60.0,
          segment_count: 15,
          avg_segment_duration_ms: 24000,
          word_count: 500,
          words_per_minute: 83.3,
          first_spoke_ms: 1000,
          last_spoke_ms: 590000,
        },
      ],
      timeline: [
        { speaker: "Alice", start_ms: 1000, end_ms: 25000 },
      ],
    };

    expectExactKeys(stats, [
      "recording_id",
      "total_duration_ms",
      "total_speakers",
      "speakers",
      "timeline",
    ]);

    const speaker: SpeakerStat = stats.speakers[0];
    expectExactKeys(speaker, [
      "name",
      "total_duration_ms",
      "percentage",
      "segment_count",
      "avg_segment_duration_ms",
      "word_count",
      "words_per_minute",
      "first_spoke_ms",
      "last_spoke_ms",
    ]);

    const entry: SpeakerTimelineEntry = stats.timeline[0];
    expectExactKeys(entry, ["speaker", "start_ms", "end_ms"]);
  });
});

describe("types-sync: TranscriptStatsResponse and TranscriptSearchResponse", () => {
  it("TranscriptStatsResponse matches backend schema", () => {
    const stats: TranscriptStatsResponse = {
      recording_id: "r1",
      segment_count: 42,
      word_count: 3500,
      unique_speakers: 3,
      speakers: ["Alice", "Bob", "Charlie"],
      avg_words_per_segment: 83.3,
      longest_segment_ms: 45000,
      shortest_segment_ms: 2000,
    };

    expectExactKeys(stats, [
      "recording_id",
      "segment_count",
      "word_count",
      "unique_speakers",
      "speakers",
      "avg_words_per_segment",
      "longest_segment_ms",
      "shortest_segment_ms",
    ]);
  });

  it("TranscriptSearchResponse matches backend schema", () => {
    const search: TranscriptSearchResponse = {
      recording_id: "r1",
      query: "roadmap",
      total_matches: 3,
      segments: [
        {
          segment_id: "seg5",
          speaker: "Alice",
          content: "Let's discuss the roadmap",
          start_ms: 15000,
          end_ms: 22000,
          match_count: 1,
        },
      ],
    };

    expectExactKeys(search, ["recording_id", "query", "total_matches", "segments"]);

    const match: TranscriptSearchMatch = search.segments[0];
    expectExactKeys(match, [
      "segment_id",
      "speaker",
      "content",
      "start_ms",
      "end_ms",
      "match_count",
    ]);
  });
});


describe("types-sync: Entity and EntityDetail", () => {
  it("Entity matches backend schema", () => {
    const entity: Entity = {
      id: "e1",
      type: "topic",
      name: "Roadmap",
      metadata: { source: "auto" },
      created_at: "2026-03-01T00:00:00Z",
    };

    expectExactKeys(entity, ["id", "type", "name", "metadata", "created_at"]);
  });

  it("EntityDetail extends Entity with relations", () => {
    const detail: EntityDetail = {
      id: "e1",
      type: "person",
      name: "Alice",
      metadata: null,
      created_at: "2026-03-01T00:00:00Z",
      relations: [
        {
          id: "rel1",
          target_id: "e2",
          target_type: "organization",
          target_name: "Acme Corp",
          relation_type: "works_at",
          context: "mentioned in Sprint Planning",
        },
      ],
    };

    expect(detail.relations).toHaveLength(1);
    expect(detail.relations[0].target_type).toBe("organization");
  });
});

describe("types-sync: RelatedRecordingsResponse", () => {
  it("RelatedRecordingsResponse matches backend schema", () => {
    const response: RelatedRecordingsResponse = {
      recording_id: "r1",
      related: [
        {
          id: "r2",
          title: "Design Review",
          created_at: "2026-03-02T00:00:00Z",
          recording_type: "meeting",
          similarity_score: 0.87,
          matching_topic: "roadmap",
        },
      ],
    };

    expectExactKeys(response, ["recording_id", "related"]);

    const related: RelatedRecording = response.related[0];
    expectExactKeys(related, [
      "id",
      "title",
      "created_at",
      "recording_type",
      "similarity_score",
      "matching_topic",
    ]);
  });
});

describe("types-sync: BulkOperationResponse and AnalyticsResponse", () => {
  it("BulkOperationResponse matches backend schema", () => {
    const resp: BulkOperationResponse = {
      processed: 5,
      failed: 1,
    };

    expectExactKeys(resp, ["processed", "failed"]);
  });

  it("AnalyticsResponse matches backend schema", () => {
    const analytics: AnalyticsResponse = {
      total_recordings: 50,
      total_duration_seconds: 36000,
      average_duration_seconds: 720,
      total_words: 45000,
      by_type: { meeting: 30, note: 15, reflection: 5 },
      by_week: [{ week: "2026-W11", count: 12 }],
    };

    expectExactKeys(analytics, [
      "total_recordings",
      "total_duration_seconds",
      "average_duration_seconds",
      "total_words",
      "by_type",
      "by_week",
    ]);
  });
});
