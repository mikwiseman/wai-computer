import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/http";
import { GlobalQAPanel } from "./GlobalQAPanel";

const mockAskDatabase = vi.fn();

vi.mock("@/lib/api", () => ({
  askDatabase: (...args: unknown[]) => mockAskDatabase(...args),
}));

const recordings = [
  {
    id: "rec-1",
    title: "Weekly Sync",
    type: "note",
    audio_url: null,
    status: "ready",
    failure_code: null,
    failure_message: null,
    uploaded_at: null,
    duration_seconds: null,
    language: "multi",
    folder_id: null,
    deleted_at: null,
    starred_at: null,
    created_at: "2026-04-16T00:00:00Z",
  },
];

describe("GlobalQAPanel", () => {
  beforeEach(() => {
    mockAskDatabase.mockReset();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("submits a scoped question and reveals sources on demand", async () => {
    mockAskDatabase.mockResolvedValueOnce({
      answer: "Budget was approved.",
      sources: [
        {
          segment_id: "seg-1",
          recording_id: "rec-1",
          recording_title: "Weekly Sync",
          speaker: "Alice",
          content: "Budget was approved.",
          start_ms: 1_000,
          end_ms: 5_000,
        },
      ],
    });

    const user = userEvent.setup();
    render(<GlobalQAPanel recordings={recordings} />);

    await user.click(screen.getByLabelText("Weekly Sync"));
    await user.type(
      screen.getByPlaceholderText("Ask about your recordings..."),
      "What did Alice decide?",
    );
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(mockAskDatabase).toHaveBeenCalledWith({
        question: "What did Alice decide?",
        recording_ids: ["rec-1"],
      });
      expect(screen.getByText("Budget was approved.")).toBeInTheDocument();
    });

    expect(screen.getByPlaceholderText("Ask about your recordings...")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "Show sources (1)" }));

    expect(screen.getAllByText(/Weekly Sync/)).toHaveLength(2);
    expect(screen.getByText("[0:01 - 0:05]")).toBeInTheDocument();
    expect(screen.getAllByText("Budget was approved.")).toHaveLength(2);
  });

  it("shows a user-facing API error", async () => {
    mockAskDatabase.mockRejectedValueOnce(new ApiError(429, "Rate limited"));

    const user = userEvent.setup();
    render(<GlobalQAPanel recordings={recordings} />);

    await user.type(screen.getByPlaceholderText("Ask about your recordings..."), "What happened?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Rate limited");
    });
  });

  it("shows a generic error for unknown failures", async () => {
    mockAskDatabase.mockRejectedValueOnce("boom");

    const user = userEvent.setup();
    render(<GlobalQAPanel recordings={[]} />);

    await user.type(screen.getByPlaceholderText("Ask about your recordings..."), "Explain this");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Unexpected error");
    });
  });
});
