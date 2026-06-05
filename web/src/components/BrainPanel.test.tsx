import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrainPanel } from "./BrainPanel";

const mockGetBrainGraph = vi.fn();
const mockListBrainSpaces = vi.fn();
const mockGetBrainSpaceHome = vi.fn();
const mockListBrainSpacePages = vi.fn();
const mockListBrainReviewPacks = vi.fn();
const mockAddBrainSpaceMember = vi.fn();
const mockAcceptBrainReviewPack = vi.fn();
const mockRejectBrainReviewPack = vi.fn();
const mockExportBrainSpace = vi.fn();

vi.mock("@/lib/api", () => ({
  acceptBrainReviewPack: (...a: unknown[]) => mockAcceptBrainReviewPack(...a),
  addBrainSpaceMember: (...a: unknown[]) => mockAddBrainSpaceMember(...a),
  exportBrainSpace: (...a: unknown[]) => mockExportBrainSpace(...a),
  getBrainGraph: (...a: unknown[]) => mockGetBrainGraph(...a),
  getBrainSpaceHome: (...a: unknown[]) => mockGetBrainSpaceHome(...a),
  listBrainReviewPacks: (...a: unknown[]) => mockListBrainReviewPacks(...a),
  listBrainSpacePages: (...a: unknown[]) => mockListBrainSpacePages(...a),
  listBrainSpaces: (...a: unknown[]) => mockListBrainSpaces(...a),
  rejectBrainReviewPack: (...a: unknown[]) => mockRejectBrainReviewPack(...a),
}));

vi.mock("@/components/EntityWikiView", () => ({
  EntityWikiView: ({ entityId }: { entityId: string }) => (
    <div data-testid="wiki-stub">wiki:{entityId}</div>
  ),
}));

function graph(overrides = {}) {
  return {
    nodes: [],
    edges: [],
    stats: { entities: 1, people: 1, topics: 0, items: 1, recordings: 1, mentions: 3 },
    overview: {
      recordings: { total: 1, summarized: 1, organized: 1, unorganized: 0 },
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
      recent_sources: [],
      llm_requests: 0,
    },
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

function claim() {
  return {
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
  };
}

function page() {
  return {
    id: "pg1",
    space_id: "s1",
    title: "Customer stage rules",
    slug: "customer-stage-rules",
    kind: "workflow",
    status: "active",
    markdown: "# Customer stage rules",
    frontmatter: {},
    version: 1,
    claims: [claim()],
    created_at: null,
    updated_at: null,
  };
}

function spaceHome(overrides = {}) {
  return {
    space: spaces().spaces[0],
    page_count: 1,
    source_count: 1,
    claim_counts: { workflow_rule: 1 },
    source_counts: { item: 1 },
    pending_review_count: 1,
    recent_pages: [page()],
    sources: [
      {
        id: "bs1",
        space_id: "s1",
        source_kind: "item",
        source_id: "i1",
        source_title: "Parent call notes",
        created_at: null,
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
    mockListBrainSpacePages.mockResolvedValue({ pages: [page()] });
    mockListBrainReviewPacks.mockResolvedValue(reviewPacks());
    mockAddBrainSpaceMember.mockResolvedValue({
      id: "m1",
      space_id: "s1",
      user_id: "u2",
      role: "viewer",
      status: "active",
    });
    mockAcceptBrainReviewPack.mockResolvedValue({});
    mockRejectBrainReviewPack.mockResolvedValue({});
    mockExportBrainSpace.mockResolvedValue({
      space: spaces().spaces[0],
      profile: "obsidian",
      files: [{ path: "Customer stage rules.md", markdown: "# Customer stage rules" }],
    });
  });

  it("renders a clear Brain home without memory proposals or a map tab", async () => {
    render(<BrainPanel />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Ask Wai with Wai School" })).toBeInTheDocument(),
    );

    expect(screen.getByRole("tab", { name: "Home" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Knowledge" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Map" })).not.toBeInTheDocument();
    expect(screen.getByText("Project Knowledge")).toBeInTheDocument();
    expect(screen.getByText("Review Knowledge")).toBeInTheDocument();
    expect(screen.getByText("Wai Memory")).toBeInTheDocument();
    expect(screen.queryByText("Memory suggestions")).not.toBeInTheDocument();
    expect(screen.getByText("Customer stage rules")).toBeInTheDocument();
    expect(screen.getByText("Bridge from Mik Personal")).toBeInTheDocument();
    expect(screen.getByText("Parent call notes")).toBeInTheDocument();
  });

  it("opens linked sources from the Brain source list", async () => {
    const onOpenSource = vi.fn();
    render(<BrainPanel onOpenSource={onOpenSource} />);
    await waitFor(() => expect(screen.getByText("Parent call notes")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Parent call notes/i }));

    expect(onOpenSource).toHaveBeenCalledWith("item", "i1");
  });

  it("opens Wai with the selected Brain scope directly", async () => {
    const onOpenWai = vi.fn();
    render(<BrainPanel onOpenWai={onOpenWai} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask Wai" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Ask Wai" }));

    await waitFor(() =>
      expect(onOpenWai).toHaveBeenCalledWith({ spaceId: "s1", spaceName: "Wai School" }),
    );
  });

  it("accepts knowledge suggestions and keeps export/share in Advanced", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Bridge from Mik Personal")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(mockAcceptBrainReviewPack).toHaveBeenCalledWith("s1", "rp1"));
    expect(screen.queryByText("Bridge from Mik Personal")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Advanced"));
    fireEvent.click(screen.getByRole("button", { name: "Obsidian" }));
    await waitFor(() => expect(mockExportBrainSpace).toHaveBeenCalledWith("s1", "obsidian"));
    expect(screen.getByText(/1 Markdown file is ready/i)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("teammate@example.com"), {
      target: { value: "teammate@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    await waitFor(() =>
      expect(mockAddBrainSpaceMember).toHaveBeenCalledWith("s1", {
        email: "teammate@example.com",
        role: "viewer",
      }),
    );
  });

  it("shows approved knowledge and opens deeper entity detail from Knowledge", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Customer stage rules")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Knowledge" }));

    expect(screen.getByText("Approved Pages")).toBeInTheDocument();
    expect(screen.getAllByText("Use 40 minute intro sessions.")).toHaveLength(2);
    expect(screen.getByText("Explore")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Anna/i }));
    expect(screen.getByTestId("wiki-stub")).toHaveTextContent("wiki:e1");
  });

  it("shows an empty state when nothing has been saved yet", async () => {
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
    mockListBrainSpaces.mockResolvedValue(spaces({ spaces: [] }));
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Start with sources")).toBeInTheDocument());
  });

  it("shows an error with a working retry", async () => {
    mockGetBrainGraph.mockRejectedValueOnce(new Error("graph boom"));
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("graph boom")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Retry/i }));
    await waitFor(() => expect(screen.getByText("Customer stage rules")).toBeInTheDocument());
  });
});
