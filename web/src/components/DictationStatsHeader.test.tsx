import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DictationStatsHeader } from "./DictationStatsHeader";
import type { DictationEntry } from "@/lib/types";

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  date.setHours(12, 0, 0, 0);
  return date.toISOString();
}

let counter = 0;
function entry(overrides: Partial<DictationEntry>): DictationEntry {
  counter += 1;
  return {
    client_entry_id: `e${counter}`,
    raw_text: "hello world",
    cleaned_text: null,
    duration_seconds: 60,
    word_count: 120,
    occurred_at: isoDaysAgo(0),
    ...overrides,
  };
}

describe("DictationStatsHeader", () => {
  it("renders nothing when there are no entries", () => {
    const { container } = render(<DictationStatsHeader entries={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("sums words and computes WPM (total words / total minutes)", () => {
    render(
      <DictationStatsHeader
        entries={[
          entry({ word_count: 120, duration_seconds: 60 }),
          entry({ word_count: 60, duration_seconds: 60 }),
        ]}
      />,
    );
    // 180 words over 120s (2 min) => 90 wpm
    expect(screen.getByText("180")).toBeTruthy();
    expect(screen.getByText("90")).toBeTruthy();
  });

  it("counts a multi-day streak (today + yesterday + 2 days ago)", () => {
    render(
      <DictationStatsHeader
        entries={[
          entry({ occurred_at: isoDaysAgo(0) }),
          entry({ occurred_at: isoDaysAgo(1) }),
          entry({ occurred_at: isoDaysAgo(2) }),
        ]}
      />,
    );
    expect(screen.getByText("day streak")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
  });

  it("returns a 0 streak when nothing today or yesterday", () => {
    render(
      <DictationStatsHeader
        entries={[entry({ occurred_at: isoDaysAgo(3) }), entry({ occurred_at: isoDaysAgo(4) })]}
      />,
    );
    expect(screen.getByText("0")).toBeTruthy();
  });
});
