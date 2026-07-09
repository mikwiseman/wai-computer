import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatDurationClock,
  formatListTimestamp,
  formatSpeakerLabel,
  formatTimestamp,
  stripInlineCodeMarkdown,
} from "./format";

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

describe("formatTimestamp", () => {
  it("formats milliseconds as M:SS", () => {
    expect(formatTimestamp(0)).toBe("0:00");
    expect(formatTimestamp(5000)).toBe("0:05");
    expect(formatTimestamp(75000)).toBe("1:15");
    expect(formatTimestamp(930000)).toBe("15:30");
  });

  it("returns an empty string for null/undefined", () => {
    expect(formatTimestamp(null)).toBe("");
    expect(formatTimestamp(undefined)).toBe("");
  });
});

describe("formatDurationClock", () => {
  it("formats sub-minute and sub-hour durations as M:SS", () => {
    expect(formatDurationClock(53)).toBe("0:53");
    expect(formatDurationClock(520)).toBe("8:40");
    expect(formatDurationClock(1720)).toBe("28:40");
  });

  it("rolls minutes into hours instead of showing 208:40", () => {
    expect(formatDurationClock(12520)).toBe("3:28:40");
    expect(formatDurationClock(3600)).toBe("1:00:00");
    expect(formatDurationClock(3661)).toBe("1:01:01");
  });

  it("returns an empty string for absent or zero durations", () => {
    expect(formatDurationClock(null)).toBe("");
    expect(formatDurationClock(undefined)).toBe("");
    expect(formatDurationClock(0)).toBe("");
  });
});

describe("formatListTimestamp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-09T15:00:00"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("labels today's timestamps", () => {
    expect(formatListTimestamp("2026-07-09T10:25:00", "ru")).toBe("Сегодня, 10:25");
    expect(formatListTimestamp("2026-07-09T10:25:00", "en")).toBe("Today, 10:25 AM");
  });

  it("labels yesterday's timestamps", () => {
    expect(formatListTimestamp("2026-07-08T18:19:00", "ru")).toBe("Вчера, 18:19");
    expect(formatListTimestamp("2026-07-08T18:19:00", "en")).toBe("Yesterday, 6:19 PM");
  });

  it("drops the year within the current year", () => {
    expect(formatListTimestamp("2026-07-02T17:02:00", "ru")).toBe("2 июля, 17:02");
    expect(formatListTimestamp("2026-07-02T17:02:00", "en")).toBe("July 2, 5:02 PM");
  });

  it("keeps the year for older dates without the Russian \"г.\" suffix", () => {
    expect(formatListTimestamp("2025-03-08T09:05:00", "ru")).toBe("8 марта 2025, 09:05");
    expect(formatListTimestamp("2025-03-08T09:05:00", "en")).toBe("March 8, 2025, 9:05 AM");
  });
});
