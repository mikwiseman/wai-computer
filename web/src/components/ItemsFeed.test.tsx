import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ItemsFeed } from "./ItemsFeed";

const mockListItems = vi.fn();
const mockGetItem = vi.fn();
const mockDeleteItem = vi.fn();
const mockCreateComparison = vi.fn();
const mockGetComparison = vi.fn();

vi.mock("@/lib/api", () => ({
  listItems: (...a: unknown[]) => mockListItems(...a),
  getItem: (...a: unknown[]) => mockGetItem(...a),
  deleteItem: (...a: unknown[]) => mockDeleteItem(...a),
  createComparison: (...a: unknown[]) => mockCreateComparison(...a),
  getComparison: (...a: unknown[]) => mockGetComparison(...a),
}));

function entry(overrides = {}) {
  return {
    id: "i1",
    source: "url",
    url: "https://x/post",
    kind: "article",
    title: "Solar Explainer",
    state: "raw",
    status: "ready",
    error: null,
    folder_id: null,
    occurred_at: null,
    created_at: new Date().toISOString(),
    has_summary: true,
    ...overrides,
  };
}

function detail() {
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
    status: "ready",
    error: null,
    folder_id: null,
    created_at: new Date().toISOString(),
    summary: {
      summary: "A clear explainer.",
      key_points: ["costs fell"],
      action_items: [],
      topics: [],
      people_mentioned: [],
      highlights: [],
      key_moments: [
        { timestamp: "00:42", moment: "Thesis", why_it_matters: "frames it", quote: null, importance: "high" },
      ],
      sentiment: "positive",
    },
  };
}

describe("ItemsFeed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListItems.mockResolvedValue({ items: [entry()], total: 1 });
    mockGetItem.mockResolvedValue(detail());
    mockDeleteItem.mockResolvedValue(undefined);
    mockCreateComparison.mockResolvedValue({
      id: "cmp-9", title: null, item_ids: ["i1", "i2"], columns: null, rows: null,
      schema_rationale: null, status: "generating", created_at: new Date().toISOString(),
    });
    mockGetComparison.mockResolvedValue({
      id: "cmp-9", title: null, item_ids: ["i1", "i2"], columns: null, rows: null,
      schema_rationale: null, status: "generating", created_at: new Date().toISOString(),
    });
  });

  it("lists items and opens detail with the key-moments table", async () => {
    render(<ItemsFeed />);
    await waitFor(() => expect(screen.getByText("Solar Explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Solar Explainer"));
    await waitFor(() => expect(screen.getByText("A clear explainer.")).toBeInTheDocument());
    expect(screen.getByText("Thesis")).toBeInTheDocument();
    expect(screen.getByText("00:42")).toBeInTheDocument();
  });

  it("filters by kind when a chip is clicked", async () => {
    render(<ItemsFeed />);
    await waitFor(() => expect(mockListItems).toHaveBeenCalledWith(undefined));
    fireEvent.click(screen.getByRole("tab", { name: "Videos" }));
    await waitFor(() => expect(mockListItems).toHaveBeenCalledWith({ kind: "video" }));
  });

  it("shows a summarizing badge for items still processing", async () => {
    mockListItems.mockResolvedValue({
      items: [entry({ has_summary: false, status: "summarizing" })],
      total: 1,
    });
    render(<ItemsFeed />);
    await waitFor(() => expect(screen.getByText(/summarizing/i)).toBeInTheDocument());
  });

  it("shows a failed badge carrying the error message as a tooltip", async () => {
    mockListItems.mockResolvedValue({
      items: [
        entry({
          has_summary: false,
          status: "failed",
          error: { code: "enqueue_failed", message: "Couldn't start processing." },
        }),
      ],
      total: 1,
    });
    render(<ItemsFeed />);
    const badge = await screen.findByText("failed");
    expect(badge).toHaveAttribute("title", "Couldn't start processing.");
  });

  it("offers a PDFs filter chip and filters by it", async () => {
    render(<ItemsFeed />);
    await waitFor(() => expect(mockListItems).toHaveBeenCalledWith(undefined));
    fireEvent.click(screen.getByRole("tab", { name: "PDFs" }));
    await waitFor(() => expect(mockListItems).toHaveBeenCalledWith({ kind: "pdf" }));
  });

  it("deletes an item and reloads", async () => {
    render(<ItemsFeed />);
    await waitFor(() => expect(screen.getByText("Solar Explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Solar Explainer"));
    await waitFor(() => expect(screen.getByText("A clear explainer.")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDeleteItem).toHaveBeenCalledWith("i1"));
  });

  it("shows an empty state", async () => {
    mockListItems.mockResolvedValue({ items: [], total: 0 });
    render(<ItemsFeed />);
    await waitFor(() => expect(screen.getByText(/Nothing here yet/i)).toBeInTheDocument());
  });

  it("surfaces load errors", async () => {
    const onError = vi.fn();
    mockListItems.mockRejectedValue(new Error("boom"));
    render(<ItemsFeed onError={onError} />);
    await waitFor(() => expect(onError).toHaveBeenCalledWith("boom"));
  });

  it("builds a comparison from 2+ selected items and opens the view", async () => {
    mockListItems.mockResolvedValue({
      items: [entry(), entry({ id: "i2", title: "Wind Explainer" })],
      total: 2,
    });
    render(<ItemsFeed />);
    await waitFor(() => expect(screen.getByText("Solar Explainer")).toBeInTheDocument());

    // No Compare action until at least 2 are selected.
    expect(screen.queryByRole("button", { name: /Compare/ })).not.toBeInTheDocument();

    const checks = screen.getAllByRole("checkbox");
    fireEvent.click(checks[0]);
    fireEvent.click(checks[1]);

    const compareBtn = await screen.findByRole("button", { name: /Compare 2/ });
    fireEvent.click(compareBtn);

    await waitFor(() =>
      expect(mockCreateComparison).toHaveBeenCalledWith({ item_ids: ["i1", "i2"] }),
    );
    // The comparison modal opens and polls the (still-generating) build.
    await waitFor(() =>
      expect(screen.getByText(/Building comparison/i)).toBeInTheDocument(),
    );
  });
});
