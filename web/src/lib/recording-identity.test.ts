import { describe, expect, it } from "vitest";

import { preserveRecordingDetailIdentity } from "./recording-identity";
import type { RecordingDetail, Segment } from "./types";

function makeSegment(overrides?: Partial<Segment>): Segment {
  return {
    id: "s1",
    speaker: "Alice",
    content: "Hello there",
    start_ms: 0,
    end_ms: 1000,
    confidence: 0.9,
    ...overrides,
  };
}

function makeDetail(overrides?: Partial<RecordingDetail>): RecordingDetail {
  return {
    id: "rec-1",
    title: "Standup",
    type: "meeting",
    audio_url: null,
    status: "completed",
    failure_code: null,
    failure_message: null,
    uploaded_at: null,
    duration_seconds: 60,
    language: "en",
    folder_id: null,
    deleted_at: null,
    starred_at: null,
    created_at: "2026-07-01T10:00:00Z",
    segments: [makeSegment()],
    summary: null,
    summary_generation: null,
    summary_audio: null,
    action_items: [],
    highlights: [],
    ...overrides,
  };
}

describe("preserveRecordingDetailIdentity", () => {
  it("returns the previous object when nothing changed, so React can bail out", () => {
    const prev = makeDetail();
    // Fresh fetch: structurally identical, referentially new.
    const next = JSON.parse(JSON.stringify(prev)) as RecordingDetail;
    expect(preserveRecordingDetailIdentity(prev, next)).toBe(prev);
  });

  it("keeps the previous segments array when only scalar fields changed", () => {
    const prev = makeDetail();
    const next = JSON.parse(JSON.stringify(prev)) as RecordingDetail;
    next.title = "Renamed";
    const merged = preserveRecordingDetailIdentity(prev, next);
    expect(merged).not.toBe(prev);
    expect(merged.title).toBe("Renamed");
    expect(merged.segments).toBe(prev.segments);
  });

  it("keeps the previous segments array while a summary is generating", () => {
    const prev = makeDetail({
      summary_generation: {
        job_id: "j1",
        recording_id: "rec-1",
        status: "running",
        stage: "drafting",
        progress_percent: 10,
        message: "Working",
        requested_at: null,
        started_at: null,
        completed_at: null,
        failed_at: null,
        error_code: null,
        error_message: null,
      },
    });
    const next = JSON.parse(JSON.stringify(prev)) as RecordingDetail;
    next.summary_generation!.progress_percent = 60;
    const merged = preserveRecordingDetailIdentity(prev, next);
    expect(merged.summary_generation?.progress_percent).toBe(60);
    expect(merged.segments).toBe(prev.segments);
  });

  it("adopts new segments when transcript content changed", () => {
    const prev = makeDetail();
    const next = JSON.parse(JSON.stringify(prev)) as RecordingDetail;
    next.segments = [
      makeSegment(),
      makeSegment({ id: "s2", content: "Another line", start_ms: 2000 }),
    ];
    const merged = preserveRecordingDetailIdentity(prev, next);
    expect(merged).toBe(next);
    expect(merged.segments).toHaveLength(2);
  });

  it("adopts new segments when a speaker assignment changed in place", () => {
    const prev = makeDetail({
      segments: [makeSegment({ raw_label: "speaker_0", display_name: null })],
    });
    const next = JSON.parse(JSON.stringify(prev)) as RecordingDetail;
    next.segments = [
      makeSegment({ raw_label: "speaker_0", display_name: "Anna", person_id: "p1" }),
    ];
    const merged = preserveRecordingDetailIdentity(prev, next);
    expect(merged.segments).toBe(next.segments);
    expect(merged.segments[0]?.display_name).toBe("Anna");
  });

  it("passes through when the previous recording is null or a different recording", () => {
    const next = makeDetail();
    expect(preserveRecordingDetailIdentity(null, next)).toBe(next);
    const other = makeDetail({ id: "rec-2" });
    expect(preserveRecordingDetailIdentity(other, next)).toBe(next);
  });
});
