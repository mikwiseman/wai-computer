import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EntityWikiView } from "./EntityWikiView";

const mockGetEntityPage = vi.fn();

vi.mock("@/lib/api", () => ({
  getEntityPage: (...a: unknown[]) => mockGetEntityPage(...a),
}));

function page(overrides = {}) {
  return {
    id: "e1",
    name: "Anna",
    type: "person",
    mention_count: 2,
    sources: [
      { source_kind: "item", source_id: "i1", title: "GPU note", context: "Anna leads it" },
      { source_kind: "recording", source_id: "r1", title: "Sync", context: null },
    ],
    related: [
      { id: "e2", name: "GPU", type: "topic", shared: 2 },
      { id: "e3", name: "Pricing", type: "topic", shared: 1 },
    ],
    ...overrides,
  };
}

describe("EntityWikiView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetEntityPage.mockResolvedValue(page());
  });

  it("renders the infobox, related entities, and source backlinks", async () => {
    render(<EntityWikiView entityId="e1" onNavigate={() => {}} />);
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
    expect(screen.getByText(/2\s+mentions/)).toBeInTheDocument();
    expect(screen.getByText("GPU note")).toBeInTheDocument(); // source backlink
    expect(screen.getByText("Anna leads it")).toBeInTheDocument(); // mention context
    expect(screen.getByText("GPU")).toBeInTheDocument(); // related entity
  });

  it("navigates when a related entity is clicked", async () => {
    const onNavigate = vi.fn();
    render(<EntityWikiView entityId="e1" onNavigate={onNavigate} />);
    await waitFor(() => expect(screen.getByText("GPU")).toBeInTheDocument());
    fireEvent.click(screen.getByText("GPU"));
    expect(onNavigate).toHaveBeenCalledWith("e2", "GPU");
  });

  it("shows an error with a working retry", async () => {
    mockGetEntityPage.mockRejectedValueOnce(new Error("page boom"));
    render(<EntityWikiView entityId="e1" onNavigate={() => {}} />);
    await waitFor(() => expect(screen.getByText("page boom")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Retry/i }));
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
  });
});
