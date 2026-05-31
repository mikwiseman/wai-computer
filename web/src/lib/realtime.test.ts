import { describe, expect, it } from "vitest";

import { parseRealtimeMessage } from "./realtime";

describe("parseRealtimeMessage", () => {
  it("parses a final result with a diarization speaker", () => {
    const raw = JSON.stringify({
      is_final: true,
      channel: { alternatives: [{ transcript: "Hello there", words: [{ speaker: 0 }] }] },
    });
    expect(parseRealtimeMessage(raw)).toEqual({
      transcript: "Hello there",
      isFinal: true,
      speaker: 0,
    });
  });

  it("parses an interim result (no speaker)", () => {
    const raw = JSON.stringify({
      is_final: false,
      channel: { alternatives: [{ transcript: "partial" }] },
    });
    expect(parseRealtimeMessage(raw)).toEqual({
      transcript: "partial",
      isFinal: false,
      speaker: null,
    });
  });

  it("returns null for an empty/whitespace transcript", () => {
    const raw = JSON.stringify({
      is_final: true,
      channel: { alternatives: [{ transcript: "   " }] },
    });
    expect(parseRealtimeMessage(raw)).toBeNull();
  });

  it("ignores non-transcript frames (Metadata, KeepAlive) and bad JSON", () => {
    expect(parseRealtimeMessage(JSON.stringify({ type: "Metadata" }))).toBeNull();
    expect(parseRealtimeMessage(JSON.stringify({ type: "KeepAlive" }))).toBeNull();
    expect(parseRealtimeMessage("not json")).toBeNull();
  });
});
