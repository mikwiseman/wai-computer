import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ItemsFeed } from "./ItemsFeed";

const mockListItems = vi.fn();
const mockGetItem = vi.fn();
const mockDeleteItem = vi.fn();

vi.mock("@/lib/api", () => ({
  listItems: (...a: unknown[]) => mockListItems(...a),
  getItem: (...a: unknown[]) => mockGetItem(...a),
  deleteItem: (...a: unknown[]) => mockDeleteItem(...a),
}));

function entry(overrides = {}) {
  return {
    id: "i1",
    source: "url",
    url: "https://x/post",
    kind: "article",
    title: "Solar Explainer",
    state: "raw",
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

  it("shows a summarizing badge for items without a summary yet", async () => {
    mockListItems.mockResolvedValue({ items: [entry({ has_summary: false })], total: 1 });
    render(<ItemsFeed />);
    await waitFor(() => expect(screen.getByText(/summarizing/i)).toBeInTheDocument());
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
});
