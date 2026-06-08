import { describe, expect, it } from "vitest";

import { mergeTurns, renderTranscript, transcriptText } from "./transcript";
import type { Segment } from "./types";

let idCounter = 0;
function seg(partial: Partial<Segment> & { content: string }): Segment {
  return {
    id: `s${idCounter++}`,
    speaker: null,
    raw_label: null,
    person_id: null,
    display_name: null,
    auto_assigned: false,
    match_confidence: null,
    start_ms: null,
    end_ms: null,
    confidence: null,
    ...partial,
  };
}

// Canonical cross-platform vectors — these match the backend
// (test_transcript_merge.py) byte-for-byte so copy/export reads the same everywhere.
const MONOLOGUE: Segment[] = [
  seg({ speaker: "speaker_0", content: "Замечания относительно сегодняшней", start_ms: 0 }),
  seg({ speaker: "speaker_0", content: "сводки.", start_ms: 2000 }),
  seg({ speaker: "speaker_0", content: "Я постараюсь подробно объяснить", start_ms: 4000 }),
  seg({ speaker: "speaker_0", content: "причину своих", start_ms: 7000 }),
  seg({ speaker: "speaker_0", content: "замечаний,", start_ms: 9000 }),
];
const MONOLOGUE_TEXT =
  "Замечания относительно сегодняшней сводки. " +
  "Я постараюсь подробно объяснить причину своих замечаний,";

const DIALOGUE: Segment[] = [
  seg({ speaker: "speaker_0", content: "Hello everyone,", start_ms: 0 }),
  seg({ speaker: "speaker_0", content: "welcome to the standup.", start_ms: 3000 }),
  seg({ speaker: "speaker_1", content: "Thanks for joining.", start_ms: 15000 }),
  seg({ speaker: "speaker_1", content: "Let's review the sprint.", start_ms: 18000 }),
  seg({ speaker: "speaker_0", content: "I finished the export feature yesterday.", start_ms: 30000 }),
];

describe("mergeTurns", () => {
  it("collapses a monologue into a single turn", () => {
    const turns = mergeTurns(MONOLOGUE);
    expect(turns).toHaveLength(1);
    expect(turns[0]!.text).toBe(MONOLOGUE_TEXT);
    expect(turns[0]!.startMs).toBe(0);
    expect(turns[0]!.segments).toHaveLength(5);
  });

  it("groups consecutive same-speaker utterances in a dialogue", () => {
    const turns = mergeTurns(DIALOGUE);
    expect(turns.map((t) => t.speaker)).toEqual(["Speaker 1", "Speaker 2", "Speaker 1"]);
    expect(turns[0]!.text).toBe("Hello everyone, welcome to the standup.");
    expect(turns[1]!.text).toBe("Thanks for joining. Let's review the sprint.");
  });

  it("orders by start_ms regardless of input order", () => {
    const turns = mergeTurns([
      seg({ speaker: "speaker_0", content: "second", start_ms: 1000 }),
      seg({ speaker: "speaker_0", content: "first", start_ms: 0 }),
    ]);
    expect(turns[0]!.text).toBe("first second");
  });

  it("skips empty and whitespace-only segments", () => {
    const turns = mergeTurns([
      seg({ speaker: "speaker_0", content: "  ", start_ms: 0 }),
      seg({ speaker: "speaker_0", content: "real", start_ms: 1000 }),
    ]);
    expect(turns).toHaveLength(1);
    expect(turns[0]!.text).toBe("real");
  });

  it("does not merge the unknown-speaker bucket with a labelled speaker", () => {
    const turns = mergeTurns([
      seg({ content: "anon", start_ms: 0 }),
      seg({ speaker: "speaker_0", content: "named", start_ms: 1000 }),
    ]);
    expect(turns.map((t) => t.key)).toEqual(["", "speaker:0"]);
  });

  it("merges an assigned person across differing raw labels", () => {
    const turns = mergeTurns([
      seg({ speaker: "speaker_0", person_id: "p1", display_name: "Anna", content: "Hi", start_ms: 0 }),
      seg({ speaker: "speaker_5", person_id: "p1", display_name: "Anna", content: "there", start_ms: 1000 }),
    ]);
    expect(turns).toHaveLength(1);
    expect(turns[0]!.speaker).toBe("Anna");
    expect(turns[0]!.text).toBe("Hi there");
  });

  it("does not insert a space before closing punctuation", () => {
    const turns = mergeTurns([
      seg({ speaker: "speaker_0", content: "Hello", start_ms: 0 }),
      seg({ speaker: "speaker_0", content: ", world", start_ms: 1000 }),
    ]);
    expect(turns[0]!.text).toBe("Hello, world");
  });

  it("keys non-numeric labels by their lowercased text and keeps them distinct", () => {
    const turns = mergeTurns([
      seg({ speaker: "Host", content: "Welcome.", start_ms: 0 }),
      seg({ speaker: "Guest", content: "Thanks.", start_ms: 1000 }),
    ]);
    expect(turns.map((t) => t.key)).toEqual(["host", "guest"]);
    expect(turns.map((t) => t.speaker)).toEqual(["Host", "Guest"]);
  });
});

describe("renderTranscript", () => {
  it("renders a monologue as prose with no labels (plain)", () => {
    expect(renderTranscript(mergeTurns(MONOLOGUE), "plain")).toBe(MONOLOGUE_TEXT);
  });

  it("leads each paragraph with the speaker for a dialogue (plain)", () => {
    expect(renderTranscript(mergeTurns(DIALOGUE), "plain")).toBe(
      "Speaker 1: Hello everyone, welcome to the standup.\n\n" +
        "Speaker 2: Thanks for joining. Let's review the sprint.\n\n" +
        "Speaker 1: I finished the export feature yesterday.",
    );
  });

  it("labels even a monologue in the speakers style", () => {
    expect(renderTranscript(mergeTurns(MONOLOGUE), "speakers")).toBe(`Speaker 1: ${MONOLOGUE_TEXT}`);
  });

  it("merges into one line per turn in the timestamped style", () => {
    expect(renderTranscript(mergeTurns(DIALOGUE), "timestamped")).toBe(
      "[Speaker 1, 0:00] Hello everyone, welcome to the standup.\n" +
        "[Speaker 2, 0:15] Thanks for joining. Let's review the sprint.\n" +
        "[Speaker 1, 0:30] I finished the export feature yesterday.",
    );
  });

  it("omits the timestamp when start_ms is missing", () => {
    const turns = mergeTurns([seg({ speaker: "speaker_0", content: "hi" })]);
    expect(renderTranscript(turns, "timestamped")).toBe("[Speaker 1] hi");
  });

  it("returns an empty string for no turns", () => {
    expect(renderTranscript([], "plain")).toBe("");
  });
});

describe("transcriptText", () => {
  it("merges and renders in one call", () => {
    expect(transcriptText(MONOLOGUE, "plain")).toBe(MONOLOGUE_TEXT);
  });
});
