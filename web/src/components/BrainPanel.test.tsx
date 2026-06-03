import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrainPanel } from "./BrainPanel";

const mockGetBrainGraph = vi.fn();
const mockListMemoryProposals = vi.fn();
const mockAcceptMemoryProposal = vi.fn();
const mockRejectMemoryProposal = vi.fn();

vi.mock("@/lib/api", () => ({
  getBrainGraph: (...a: unknown[]) => mockGetBrainGraph(...a),
  listMemoryProposals: (...a: unknown[]) => mockListMemoryProposals(...a),
  acceptMemoryProposal: (...a: unknown[]) => mockAcceptMemoryProposal(...a),
  rejectMemoryProposal: (...a: unknown[]) => mockRejectMemoryProposal(...a),
}));

// The force graph is canvas/WebGL — stub it; its mapping logic is tested in
// BrainGraphView.test.tsx.
vi.mock("@/components/BrainGraphView", () => ({
  BrainGraphView: () => <div data-testid="brain-graph-stub">graph</div>,
}));

vi.mock("@/components/EntityWikiView", () => ({
  EntityWikiView: ({ entityId }: { entityId: string }) => (
    <div data-testid="wiki-stub">wiki:{entityId}</div>
  ),
}));

function graph(overrides = {}) {
  return {
    nodes: [
      { id: "e1", label: "Anna", kind: "person", degree: 3 },
      { id: "e2", label: "GPU", kind: "topic", degree: 5 },
      { id: "e3", label: "Pricing", kind: "topic", degree: 1 },
      { id: "item:i1", label: "Solar Note", kind: "item", degree: 0 },
    ],
    edges: [],
    stats: { entities: 3, people: 1, topics: 2, items: 1, recordings: 1, mentions: 9 },
    overview: {
      recordings: { total: 2, summarized: 1, organized: 1, unorganized: 1 },
      materials: { total: 1, summarized: 1, organized: 1, unorganized: 0 },
      pending_review_count: 1,
      top_entities: [
        {
          id: "e1",
          name: "Anna",
          type: "person",
          source_count: 2,
          recording_count: 1,
          material_count: 1,
        },
      ],
      recent_sources: [
        {
          id: "recording:r1",
          source_kind: "recording",
          source_id: "r1",
          title: "Launch sync",
          entity_count: 2,
          organized_at: null,
        },
      ],
      llm_requests: 0,
    },
    ...overrides,
  };
}

function proposals(overrides = {}) {
  return {
    proposals: [
      {
        id: "p1",
        kind: "memory_upsert",
        risk: "high",
        block_label: "human",
        operation: "rewrite",
        content: "Anna is the launch owner.",
        target_line: null,
        summary: "rewrite -> human",
        confidence: 0.95,
        authority: "self",
        evidence: [{ source_kind: "recording", title: "Launch sync" }],
        status: "pending",
        decision_reason: null,
        created_at: null,
        decided_at: null,
      },
    ],
    pending_count: 1,
    ...overrides,
  };
}

describe("BrainPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetBrainGraph.mockResolvedValue(graph());
    mockListMemoryProposals.mockResolvedValue(proposals());
    mockAcceptMemoryProposal.mockResolvedValue({});
    mockRejectMemoryProposal.mockResolvedValue({});
  });

  it("renders the overview with coverage, top entities, and review evidence", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Coverage")).toBeInTheDocument());
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.getAllByText("Needs review").length).toBeGreaterThan(0);
    expect(screen.getByText("Anna is the launch owner.")).toBeInTheDocument();
    expect(screen.getAllByText(/Launch sync/i).length).toBeGreaterThan(0);
    expect(screen.getByText("1 recordings · 1 materials")).toBeInTheDocument();
  });

  it("renders categorized entities sorted by degree (sources excluded)", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Index" }));
    expect(screen.getByText("People")).toBeInTheDocument();
    expect(screen.getByText("Topics")).toBeInTheDocument();

    const topics = screen.getByText("Topics").closest("section") as HTMLElement;
    const chips = topics.querySelectorAll(".brain-panel__chip span");
    expect(chips[0].textContent).toBe("GPU"); // degree 5 first
    expect(chips[1].textContent).toBe("Pricing"); // degree 1

    expect(screen.queryByText("Solar Note")).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no entities", async () => {
    mockGetBrainGraph.mockResolvedValue(
      graph({
        nodes: [],
        stats: { entities: 0 },
        overview: {
          recordings: { total: 0, summarized: 0, organized: 0, unorganized: 0 },
          materials: { total: 0, summarized: 0, organized: 0, unorganized: 0 },
          pending_review_count: 0,
          top_entities: [],
          recent_sources: [],
          llm_requests: 0,
        },
      }),
    );
    mockListMemoryProposals.mockResolvedValue(proposals({ proposals: [], pending_count: 0 }));
    render(<BrainPanel />);
    await waitFor(() =>
      expect(screen.getByText(/No organized entities yet/i)).toBeInTheDocument(),
    );
  });

  it("shows an error with a working retry (no silent fallback)", async () => {
    mockGetBrainGraph.mockRejectedValueOnce(new Error("graph boom"));
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("graph boom")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Retry/i }));
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
  });

  it("switches to the Graph tab", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Graph" }));
    expect(screen.getByTestId("brain-graph-stub")).toBeInTheDocument();
  });

  it("opens the Wiki for a clicked Index entity", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Anna"));
    expect(screen.getByTestId("wiki-stub")).toHaveTextContent("wiki:e1");
  });
});
