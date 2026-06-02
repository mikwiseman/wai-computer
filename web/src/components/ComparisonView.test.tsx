import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ComparisonView } from "./ComparisonView";

const mockGetComparison = vi.fn();

vi.mock("@/lib/api", () => ({
  getComparison: (...args: unknown[]) => mockGetComparison(...args),
}));

function readySet(overrides = {}) {
  return {
    id: "cmp-1",
    title: "Cameras compared",
    item_ids: ["i1", "i2"],
    status: "ready",
    schema_rationale: "Compared by price and weight.",
    columns: [
      { name: "Price", type: "text" },
      { name: "Weight", type: "text" },
    ],
    rows: [
      { item_id: "i1", title: "Alpha", values: { Price: "$10", Weight: null } },
      { item_id: "i2", title: "Beta", values: { Price: "$20", Weight: "2kg" } },
    ],
    created_at: "2026-06-02T00:00:00Z",
    ...overrides,
  };
}

describe("ComparisonView", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the comparison table when ready", async () => {
    mockGetComparison.mockResolvedValue(readySet());
    render(<ComparisonView comparisonId="cmp-1" onClose={() => {}} />);

    await waitFor(() =>
      expect(screen.getByText("Cameras compared")).toBeInTheDocument(),
    );
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getByText("Weight")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("$20")).toBeInTheDocument();
    // A null cell renders as an em dash — never a blank that reads as "0/false".
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });

  it("shows a building state while still generating", async () => {
    mockGetComparison.mockResolvedValue(
      readySet({ status: "generating", columns: null, rows: null }),
    );
    render(<ComparisonView comparisonId="cmp-1" onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByText(/Building comparison/i)).toBeInTheDocument(),
    );
  });

  it("surfaces the reason when a build failed", async () => {
    mockGetComparison.mockResolvedValue(
      readySet({
        status: "failed",
        columns: null,
        rows: null,
        schema_rationale: "Only 1 item survived — need at least 2 to compare.",
      }),
    );
    render(<ComparisonView comparisonId="cmp-1" onClose={() => {}} />);
    await waitFor(() =>
      expect(
        screen.getByText(/Only 1 item survived/i),
      ).toBeInTheDocument(),
    );
  });

  it("closes via the Close button", async () => {
    const onClose = vi.fn();
    mockGetComparison.mockResolvedValue(readySet());
    render(<ComparisonView comparisonId="cmp-1" onClose={onClose} />);
    await waitFor(() =>
      expect(screen.getByText("Cameras compared")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /close comparison/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
