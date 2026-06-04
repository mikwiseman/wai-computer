import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrainPanel } from "./BrainPanel";

const mockGetBrainGraph = vi.fn();
const mockListBrainSpaces = vi.fn();
const mockGetBrainSpaceHome = vi.fn();
const mockListBrainReviewPacks = vi.fn();
const mockAddBrainSpaceMember = vi.fn();
const mockBuildBrainContext = vi.fn();
const mockAcceptBrainReviewPack = vi.fn();
const mockRejectBrainReviewPack = vi.fn();
const mockExportBrainSpace = vi.fn();
const mockListMemoryProposals = vi.fn();
const mockAcceptMemoryProposal = vi.fn();
const mockRejectMemoryProposal = vi.fn();

vi.mock("@/lib/api", () => ({
  acceptBrainReviewPack: (...a: unknown[]) => mockAcceptBrainReviewPack(...a),
  addBrainSpaceMember: (...a: unknown[]) => mockAddBrainSpaceMember(...a),
  buildBrainContext: (...a: unknown[]) => mockBuildBrainContext(...a),
  getBrainGraph: (...a: unknown[]) => mockGetBrainGraph(...a),
  getBrainSpaceHome: (...a: unknown[]) => mockGetBrainSpaceHome(...a),
  listBrainReviewPacks: (...a: unknown[]) => mockListBrainReviewPacks(...a),
  listBrainSpaces: (...a: unknown[]) => mockListBrainSpaces(...a),
  rejectBrainReviewPack: (...a: unknown[]) => mockRejectBrainReviewPack(...a),
  exportBrainSpace: (...a: unknown[]) => mockExportBrainSpace(...a),
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

function spaces(overrides = {}) {
  return {
    spaces: [
      {
        id: "s1",
        owner_user_id: "u1",
        name: "Wai School",
        slug: "wai-school",
        kind: "work",
        engine_profile: "waibrain",
        visibility: "private",
        description: null,
        role: "owner",
        created_at: null,
        updated_at: null,
      },
    ],
    ...overrides,
  };
}

function spaceHome(overrides = {}) {
  return {
    space: spaces().spaces[0],
    page_count: 2,
    source_count: 1,
    claim_counts: { fact: 1, workflow_rule: 1 },
    source_counts: { item: 1 },
    pending_review_count: 1,
    recent_pages: [
      {
        id: "pg1",
        space_id: "s1",
        title: "Customer stage rules",
        slug: "customer-stage-rules",
        kind: "workflow",
        status: "active",
        markdown: "# Customer stage rules",
        frontmatter: {},
        version: 1,
        claims: [
          {
            id: "c1",
            space_id: "s1",
            page_id: "pg1",
            kind: "workflow_rule",
            status: "active",
            text: "Use 40 minute intro sessions.",
            confidence: 0.9,
            authority: "self",
            evidence: [],
            source_refs: null,
            created_at: null,
            accepted_at: null,
          },
        ],
        created_at: null,
        updated_at: null,
      },
    ],
    engine_profiles: ["waibrain", "obsidian", "gbrain", "mempalace"],
    ...overrides,
  };
}

function reviewPacks(overrides = {}) {
  return {
    review_packs: [
      {
        id: "rp1",
        space_id: "s1",
        kind: "bridge",
        risk: "medium",
        status: "pending",
        title: "Bridge from Mik Personal",
        summary: "Review pages: Customer stage rules from Mik Personal.",
        proposals: [],
        evidence: null,
        created_by_user_id: "u1",
        decided_by_user_id: null,
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
    mockListBrainSpaces.mockResolvedValue(spaces());
    mockGetBrainSpaceHome.mockResolvedValue(spaceHome());
    mockListBrainReviewPacks.mockResolvedValue(reviewPacks());
    mockAddBrainSpaceMember.mockResolvedValue({
      id: "m1",
      space_id: "s1",
      user_id: "u2",
      role: "viewer",
      status: "active",
    });
    mockBuildBrainContext.mockResolvedValue({
      space: spaces().spaces[0],
      markdown: "# Wai School context\n\n- Use 40 minute intro sessions.",
      claim_count: 2,
    });
    mockAcceptBrainReviewPack.mockResolvedValue({});
    mockRejectBrainReviewPack.mockResolvedValue({});
    mockExportBrainSpace.mockResolvedValue({
      space: spaces().spaces[0],
      profile: "obsidian",
      files: [{ path: "Customer stage rules.md", markdown: "# Customer stage rules" }],
    });
    mockListMemoryProposals.mockResolvedValue(proposals());
    mockAcceptMemoryProposal.mockResolvedValue({});
    mockRejectMemoryProposal.mockResolvedValue({});
  });

  it("renders the overview with coverage, top entities, and review evidence", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Coverage")).toBeInTheDocument());
    expect(screen.getAllByText("Space").length).toBeGreaterThan(0);
    expect(screen.getByDisplayValue("Wai School")).toBeInTheDocument();
    expect(screen.getByText("Prepare context")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Share" })).toBeDisabled();
    expect(screen.getByText("Customer stage rules")).toBeInTheDocument();
    expect(screen.getByText("Bridge from Mik Personal")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.getAllByText("Needs review").length).toBeGreaterThan(0);
    expect(screen.getByText("Anna is the launch owner.")).toBeInTheDocument();
    expect(screen.getAllByText(/Launch sync/i).length).toBeGreaterThan(0);
    expect(screen.getByText("1 recordings · 1 materials")).toBeInTheDocument();
  });

  it("opens the source behind a recently organized row", async () => {
    const onOpenSource = vi.fn();
    render(<BrainPanel onOpenSource={onOpenSource} />);
    await waitFor(() => expect(screen.getByText("Recently organized")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Launch sync/i }));

    expect(onOpenSource).toHaveBeenCalledWith("recording", "r1");
  });

  it("accepts a Space review pack and exports the selected Space", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Bridge from Mik Personal")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Accept review pack/i }));
    await waitFor(() => expect(mockAcceptBrainReviewPack).toHaveBeenCalledWith("s1", "rp1"));
    expect(screen.queryByText("Bridge from Mik Personal")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "obsidian" }));
    await waitFor(() => expect(mockExportBrainSpace).toHaveBeenCalledWith("s1", "obsidian"));
    expect(screen.getByText(/obsidian export ready/i)).toBeInTheDocument();
  });

  it("shares a Space and prepares assistant context", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Prepare context")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await waitFor(() =>
      expect(mockBuildBrainContext).toHaveBeenCalledWith("s1", {
        task: "Use this Space as the source of truth.",
        limit: 80,
      }),
    );
    expect(screen.getByText(/2 claims ready/i)).toBeInTheDocument();
    expect(screen.getByText("Context preview")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("teammate@example.com"), {
      target: { value: "teammate@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Share" }));

    await waitFor(() =>
      expect(mockAddBrainSpaceMember).toHaveBeenCalledWith("s1", {
        email: "teammate@example.com",
        role: "viewer",
      }),
    );
    expect(screen.getByText(/Shared with teammate@example.com as viewer/i)).toBeInTheDocument();
  });

  it("renders categorized entities sorted by degree (sources excluded)", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Index" }));
    await waitFor(() => expect(screen.getByText("People")).toBeInTheDocument());
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
