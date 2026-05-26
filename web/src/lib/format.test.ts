import { describe, expect, it } from "vitest";

import { formatSpeakerLabel, stripInlineCodeMarkdown } from "./format";

describe("formatSpeakerLabel", () => {
  it("prefers the human-assigned display name", () => {
    expect(formatSpeakerLabel("speaker_2", "Speaker 2", "Mik")).toBe("Mik");
  });

  it("upgrades lowercase machine speaker ids to a 1-based label", () => {
    expect(formatSpeakerLabel("speaker_0", null, null)).toBe("Speaker 1");
    expect(formatSpeakerLabel("speaker_3", null, null)).toBe("Speaker 4");
  });

  it("upgrades the diariser's Speaker 0 label to a 1-based label", () => {
    expect(formatSpeakerLabel("Speaker 0", "Speaker 0", null)).toBe("Speaker 1");
  });

  it("returns named speakers as-is", () => {
    expect(formatSpeakerLabel("Mik", null, null)).toBe("Mik");
  });

  it("localises the fallback speaker word into Russian", () => {
    expect(formatSpeakerLabel("speaker_0", null, null, "ru")).toBe("Спикер 1");
    expect(formatSpeakerLabel(null, null, null, "ru")).toBe("Спикер 1");
  });

  it("treats blank inputs as Speaker 1", () => {
    expect(formatSpeakerLabel(null, null, null)).toBe("Speaker 1");
    expect(formatSpeakerLabel("", "", "")).toBe("Speaker 1");
  });

  it("falls back to raw_label when speaker is missing", () => {
    expect(formatSpeakerLabel(null, "speaker_4", null)).toBe("Speaker 5");
  });
});

describe("stripInlineCodeMarkdown", () => {
  it("removes inline backtick code fences but keeps the inner text", () => {
    expect(
      stripInlineCodeMarkdown("We talked about `Minecraft` and `Nintendo`."),
    ).toBe("We talked about Minecraft and Nintendo.");
  });

  it("leaves prose without backticks untouched", () => {
    expect(stripInlineCodeMarkdown("Plain transcript text.")).toBe(
      "Plain transcript text.",
    );
  });

  it("handles empty input", () => {
    expect(stripInlineCodeMarkdown("")).toBe("");
  });
});
