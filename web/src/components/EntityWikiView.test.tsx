import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    overview: "Anna appears in 2 sources. Latest source: GPU note.",
    facts: [{ id: "fact-1", text: "Anna owns the GPU launch.", citation_ids: ["item:i1"] }],
    citations: [
      {
        id: "item:i1",
        source_kind: "item",
        source_id: "i1",
        title: "GPU note",
        context: "Anna leads it",
        occurred_at: null,
      },
      {
        id: "recording:r1",
        source_kind: "recording",
        source_id: "r1",
        title: "Sync",
        context: null,
        occurred_at: null,
      },
    ],
    timeline: [
      {
        id: "event-1",
        title: "GPU launch ownership",
        description: "Anna was assigned ownership.",
        occurred_at: null,
        citation_ids: ["item:i1"],
      },
    ],
    related_explanations: [
      {
        id: "e2",
        name: "GPU",
        type: "topic",
        shared: 2,
        explanation: "Shares 2 sources: GPU note, Sync.",
        citation_ids: ["item:i1", "recording:r1"],
      },
    ],
    questions: [{ id: "question-1", text: "What GPU ships first?", citation_ids: ["item:i1"] }],
    actions: [
      {
        id: "action-1",
        text: "Ask Anna for the launch date",
        owner: "Mik",
        due_date: null,
        status: "pending",
        citation_ids: ["item:i1"],
      },
    ],
    cache_status: "hit",
    ...overrides,
  };
}

describe("EntityWikiView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetEntityPage.mockResolvedValue(page());
  });

  it("renders the rich cached wiki page", async () => {
    render(<EntityWikiView entityId="e1" onNavigate={() => {}} />);
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
    expect(screen.getByText(/2\s+mentions/)).toBeInTheDocument();
    expect(screen.getByText(/Latest source: GPU note/)).toBeInTheDocument();
    expect(screen.getByText("Anna owns the GPU launch.")).toBeInTheDocument();
    expect(screen.getByText("GPU launch ownership")).toBeInTheDocument();
    expect(screen.getByText("What GPU ships first?")).toBeInTheDocument();
    expect(screen.getByText("Ask Anna for the launch date")).toBeInTheDocument();
    expect(screen.getByText("Shares 2 sources: GPU note, Sync.")).toBeInTheDocument();
    expect(screen.getAllByText("GPU note").length).toBeGreaterThan(0);
    expect(screen.getByText("Anna leads it")).toBeInTheDocument();
  });

  it("navigates when a related entity is clicked", async () => {
    const onNavigate = vi.fn();
    render(<EntityWikiView entityId="e1" onNavigate={onNavigate} />);
    await waitFor(() => expect(screen.getByText("GPU")).toBeInTheDocument());
    fireEvent.click(screen.getByText("GPU"));
    expect(onNavigate).toHaveBeenCalledWith("e2", "GPU");
  });

  it("opens a cited source from the page", async () => {
    const onOpenSource = vi.fn();
    render(
      <EntityWikiView entityId="e1" onNavigate={() => {}} onOpenSource={onOpenSource} />,
    );

    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
    const citations = screen.getByRole("heading", { name: "Citations" }).closest("section");
    expect(citations).not.toBeNull();
    fireEvent.click(
      within(citations as HTMLElement).getByRole("button", { name: "Open source: GPU note" }),
    );

    expect(onOpenSource).toHaveBeenCalledWith("item", "i1");
  });

  it("shows an error with a working retry", async () => {
    mockGetEntityPage.mockRejectedValueOnce(new Error("page boom"));
    render(<EntityWikiView entityId="e1" onNavigate={() => {}} />);
    await waitFor(() => expect(screen.getByText("page boom")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Retry/i }));
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
  });
});
