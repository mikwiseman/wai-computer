import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ItemDetail } from "./ItemDetail";

const mockGetItem = vi.fn();

vi.mock("@/lib/api", () => ({
  getItem: (...a: unknown[]) => mockGetItem(...a),
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

  it("shows the share-the-file notice for needs_input items", async () => {
    mockGetItem.mockResolvedValue(detail({ state: "needs_input", summary: null }));
    render(<ItemDetail itemId="i1" />);
    await waitFor(() =>
      expect(screen.getByText(/share the file or paste the text/i)).toBeInTheDocument(),
    );
  });

  it("surfaces load errors", async () => {
    const onError = vi.fn();
    mockGetItem.mockRejectedValue(new Error("nope"));
    render(<ItemDetail itemId="i1" onError={onError} />);
    await waitFor(() => expect(onError).toHaveBeenCalledWith("nope"));
  });
});
