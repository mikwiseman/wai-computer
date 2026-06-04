import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ItemDetail } from "./ItemDetail";

const mockGetItem = vi.fn();
const mockReprocessItem = vi.fn();
const mockDeleteItem = vi.fn();

vi.mock("@/lib/api", () => ({
  deleteItem: (...a: unknown[]) => mockDeleteItem(...a),
  getItem: (...a: unknown[]) => mockGetItem(...a),
  reprocessItem: (...a: unknown[]) => mockReprocessItem(...a),
}));

function detail(overrides = {}) {
  return {
    id: "i1",
    source: "url",
    source_ref: null,
    url: "https://x/post",
    kind: "article",
    title: "Solar Explainer",
    body: "...",
    occurred_at: null,
    state: "raw",
    folder_id: null,
    created_at: "2026-06-01T00:00:00Z",
    summary: {
      summary: "A clear explainer about solar.",
      key_points: ["costs fell", "storage grew"],
      action_items: [],
      topics: [],
      people_mentioned: [],
      highlights: [],
      key_moments: [
        { timestamp: null, moment: "Thesis", why_it_matters: "frames it", quote: null, importance: "high" },
      ],
      sentiment: "positive",
    },
    ...overrides,
  };
}

describe("ItemDetail", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders summary, key moments, and key points", async () => {
    mockGetItem.mockResolvedValue(detail());
    render(<ItemDetail itemId="i1" />);
    await waitFor(() => expect(screen.getByText("Solar Explainer")).toBeInTheDocument());
    expect(screen.getByText("A clear explainer about solar.")).toBeInTheDocument();
    expect(screen.getByText("Thesis")).toBeInTheDocument();
    expect(screen.getByText("costs fell")).toBeInTheDocument();
  });

  it("offers recovery (error + paste box) for a needs_input item", async () => {
    mockGetItem.mockResolvedValue(
      detail({
        status: "needs_input",
        state: "needs_input",
        summary: null,
        error: { code: "youtube_no_transcript", message: "This video has no transcript." },
      }),
    );
    render(<ItemDetail itemId="i1" />);
    await waitFor(() =>
      expect(screen.getByText("This video has no transcript.")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("item-recover-input")).toBeInTheDocument();
  });

  it("reprocesses a needs_input item with pasted text", async () => {
    mockGetItem.mockResolvedValue(
      detail({ status: "needs_input", state: "needs_input", summary: null }),
    );
    mockReprocessItem.mockResolvedValue(
      detail({ status: "summarizing", state: "raw", body: "pasted", summary: null }),
    );
    render(<ItemDetail itemId="i1" />);
    await waitFor(() =>
      expect(screen.getByTestId("item-recover-input")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId("item-recover-input"), {
      target: { value: "pasted article text" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Process pasted text/i }));
    await waitFor(() =>
      expect(mockReprocessItem).toHaveBeenCalledWith("i1", { body: "pasted article text" }),
    );
    // Once reprocessing starts (no longer needs_input) the recovery box disappears.
    await waitFor(() =>
      expect(screen.queryByTestId("item-recover-input")).not.toBeInTheDocument(),
    );
  });

  it("deletes the item and notifies the parent", async () => {
    const onDeleted = vi.fn();
    mockGetItem.mockResolvedValue(detail());
    mockDeleteItem.mockResolvedValue(undefined);

    render(<ItemDetail itemId="i1" onDeleted={onDeleted} />);

    await waitFor(() => expect(screen.getByText("Solar Explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(mockDeleteItem).toHaveBeenCalledWith("i1"));
    expect(onDeleted).toHaveBeenCalledWith("i1");
  });

  it("refreshes processing items until the summary lands", async () => {
    mockGetItem
      .mockResolvedValueOnce(detail({ status: "summarizing", state: "raw", summary: null }))
      .mockResolvedValueOnce(detail({ status: "ready", state: "raw" }));

    render(<ItemDetail itemId="i1" pollIntervalMs={1} />);

    await waitFor(() => expect(screen.getByTestId("item-processing")).toBeInTheDocument());
    await waitFor(() => expect(mockGetItem).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByText("A clear explainer about solar.")).toBeInTheDocument(),
    );
  });

  it("surfaces load errors", async () => {
    const onError = vi.fn();
    mockGetItem.mockRejectedValue(new Error("nope"));
    render(<ItemDetail itemId="i1" onError={onError} />);
    await waitFor(() => expect(onError).toHaveBeenCalledWith("nope"));
  });
});
