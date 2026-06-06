import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrainPanel } from "./BrainPanel";

const mockGetBrainMirror = vi.fn();
const mockListBrainMaps = vi.fn();
const mockCreateBrainMap = vi.fn();
const mockUpdateBrainMap = vi.fn();
const mockRefreshBrainMap = vi.fn();
const mockListEntities = vi.fn();
const mockListBrainSpaces = vi.fn();
const mockGetBrainSpaceHome = vi.fn();
const mockListBrainReviewPacks = vi.fn();
const mockAddBrainSpaceMember = vi.fn();
const mockAcceptBrainReviewPack = vi.fn();
const mockRejectBrainReviewPack = vi.fn();
const mockExportBrainSpace = vi.fn();

type MockFlowNode = {
  id: string;
  position: {
    x: number;
    y: number;
  };
  data: {
    onOpen?: () => void;
    node: {
      title: string;
    };
  };
};

vi.mock("@xyflow/react", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  return {
    Background: () => null,
    Controls: () => null,
    Handle: () => null,
    MiniMap: () => null,
    Position: { Left: "left", Right: "right" },
    ReactFlow: ({ nodes, children }: { nodes: MockFlowNode[]; children: ReactNode }) =>
      React.createElement(
        "div",
        { "data-testid": "flow" },
        nodes.map((node) =>
          React.createElement(
            "button",
            {
              key: node.id,
              type: "button",
              "data-node-id": node.id,
              "data-x": String(node.position.x),
              "data-y": String(node.position.y),
              onClick: node.data.onOpen,
              disabled: !node.data.onOpen,
            },
            node.data.node.title,
          ),
        ),
        children,
      ),
    useEdgesState: <T,>(initial: T[]) => {
      const [state, setState] = React.useState<T[]>(initial);
      return [state, setState, vi.fn()];
    },
    useNodesState: <T,>(initial: T[]) => {
      const [state, setState] = React.useState<T[]>(initial);
      return [state, setState, vi.fn()];
    },
  };
});

vi.mock("@/lib/api", () => ({
  acceptBrainReviewPack: (...a: unknown[]) => mockAcceptBrainReviewPack(...a),
  addBrainSpaceMember: (...a: unknown[]) => mockAddBrainSpaceMember(...a),
  createBrainMap: (...a: unknown[]) => mockCreateBrainMap(...a),
  exportBrainSpace: (...a: unknown[]) => mockExportBrainSpace(...a),
  getBrainMirror: (...a: unknown[]) => mockGetBrainMirror(...a),
  getBrainSpaceHome: (...a: unknown[]) => mockGetBrainSpaceHome(...a),
  listBrainMaps: (...a: unknown[]) => mockListBrainMaps(...a),
  listBrainReviewPacks: (...a: unknown[]) => mockListBrainReviewPacks(...a),
  listBrainSpaces: (...a: unknown[]) => mockListBrainSpaces(...a),
  listEntities: (...a: unknown[]) => mockListEntities(...a),
  refreshBrainMap: (...a: unknown[]) => mockRefreshBrainMap(...a),
  rejectBrainReviewPack: (...a: unknown[]) => mockRejectBrainReviewPack(...a),
  updateBrainMap: (...a: unknown[]) => mockUpdateBrainMap(...a),
}));

vi.mock("@/components/EntityWikiView", () => ({
  EntityWikiView: ({ entityId }: { entityId: string }) => (
    <div data-testid="wiki-stub">wiki:{entityId}</div>
  ),
}));

function projection(overrides = {}) {
  return {
    version: 1,
    map_type: "live_mirror",
    title: "Live Mirror",
    prompt: "Live Mirror",
    summary: "Live Mirror from 1 source(s) and 1 linked node(s).",
    nodes: [
      {
        id: "lens:root",
        kind: "lens",
        title: "Live Mirror",
        body: "Live Mirror",
        lane: "center",
        citation_ids: [],
        position: { x: 0, y: 0 },
      },
      {
        id: "source:item:item-1",
        kind: "source",
        title: "Launch notes",
        body: "Pricing needs legal sign-off.",
        lane: "sources",
        source_kind: "item",
        source_id: "item-1",
        citation_ids: ["item:item-1"],
        position: { x: -340, y: -160 },
      },
      {
        id: "entity:e1",
        kind: "entity",
        title: "Anna",
        body: "person",
        lane: "people",
        entity_id: "e1",
        entity_type: "person",
        citation_ids: ["item:item-1"],
        position: { x: 340, y: 40 },
      },
    ],
    edges: [
      {
        id: "edge:lens:root:source:item:item-1",
        source: "lens:root",
        target: "source:item:item-1",
        kind: "supports",
        label: "supports",
        citation_ids: ["item:item-1"],
      },
    ],
    citations: [
      {
        id: "item:item-1",
        source_kind: "item",
        source_id: "item-1",
        title: "Launch notes",
        kind: "note",
        created_at: "2026-06-05T10:00:00Z",
      },
    ],
    freshness: { newest_source_at: "2026-06-05T10:00:00Z", weeks_since: 0, stale: false },
    stats: { entities: 1 },
    source_fingerprint: "mirror",
    ...overrides,
  };
}

function crowdedProjection() {
  const sourceNodes = Array.from({ length: 12 }, (_, index) => ({
    id: `source:item:item-${index + 1}`,
    kind: "source",
    title: `Source ${index + 1}`,
    body: `Source detail ${index + 1}`,
    lane: "sources",
    source_kind: "item",
    source_id: `item-${index + 1}`,
    citation_ids: [`item:item-${index + 1}`],
    position: { x: 0, y: 0 },
  }));
  const entityNodes = Array.from({ length: 12 }, (_, index) => ({
    id: `entity:e${index + 1}`,
    kind: "entity",
    title: `Entity ${index + 1}`,
    body: "project",
    lane: "projects",
    entity_id: `e${index + 1}`,
    entity_type: "project",
    citation_ids: [`item:item-${(index % 12) + 1}`],
    position: { x: 0, y: 0 },
  }));
  const nodes = [
    {
      id: "lens:root",
      kind: "lens",
      title: "Project focus",
      body: "What matters now",
      lane: "center",
      citation_ids: [],
      position: { x: 0, y: 0 },
    },
    ...sourceNodes,
    ...entityNodes,
  ];

  return projection({
    title: "Crowded map",
    summary: "Crowded map from 12 sources and 12 linked nodes.",
    nodes,
    edges: nodes
      .filter((node) => node.id !== "lens:root")
      .map((node) => ({
        id: `edge:lens:root:${node.id}`,
        source: "lens:root",
        target: node.id,
        kind: "supports",
        label: "supports",
        citation_ids: node.citation_ids,
      })),
    citations: sourceNodes.map((node) => ({
      id: node.citation_ids[0],
      source_kind: "item",
      source_id: node.source_id,
      title: node.title,
      kind: "note",
      created_at: "2026-06-05T10:00:00Z",
    })),
  });
}

function briefing(overrides = {}) {
  return {
    mode: "focused",
    headline: "Project State",
    focus_note: "Showing 3 of 12 source(s) and 8 of 24 linked node(s).",
    freshness_note: "Evidence is current.",
    coverage: {
      visible_sources: 3,
      total_sources: 12,
      visible_entities: 8,
      total_entities: 24,
    },
    top_sources: [
      {
        id: "item:item-1",
        source_kind: "item",
        source_id: "item-1",
        title: "Launch notes",
        kind: "note",
        created_at: "2026-06-05T10:00:00Z",
      },
    ],
    top_entities: [
      {
        id: "e1",
        type: "person",
        name: "Anna",
        citation_count: 1,
      },
    ],
    suggested_questions: [
      "What are the active risks?",
      "What changed since the last update?",
      "What should happen next?",
    ],
    ...overrides,
  };
}

function revision(overrides = {}) {
  const baseProjection = projection({
    map_type: "project_state",
    title: "Hiring map",
    prompt: "Map hiring",
    summary: "Project State from 1 source(s) and 1 linked node(s).",
    briefing: briefing(),
  });
  return {
    id: "rev-1",
    map_id: "map-1",
    revision_index: 1,
    projection: baseProjection,
    source_fingerprint: "abc",
    source_count: 1,
    freshness: baseProjection.freshness,
    diff: {
      nodes_added: 3,
      nodes_removed: 0,
      edges_added: 1,
      edges_removed: 0,
      sources_added: 1,
      sources_removed: 0,
      changed: true,
    },
    citations: baseProjection.citations,
    compiled_at: "2026-06-05T10:00:00Z",
    created_at: "2026-06-05T10:00:00Z",
    ...overrides,
  };
}

function brainMap(overrides = {}) {
  return {
    id: "map-1",
    space_id: null,
    title: "Hiring map",
    prompt: "Map hiring",
    map_type: "project_state",
    origin: "brain",
    status: "draft",
    source_scope: null,
    layout: {},
    current_revision_id: "rev-1",
    current_revision: revision(),
    created_at: "2026-06-05T10:00:00Z",
    updated_at: "2026-06-05T10:00:00Z",
    ...overrides,
  };
}

function entities() {
  return [
    { id: "e1", type: "person", name: "Anna", metadata: null, created_at: "", mention_count: 2, source_count: 2 },
    { id: "e2", type: "topic", name: "Pricing", metadata: null, created_at: "", mention_count: 1, source_count: 1 },
  ];
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
    page_count: 1,
    source_count: 1,
    claim_counts: { workflow_rule: 1 },
    source_counts: { item: 1 },
    pending_review_count: 1,
    recent_pages: [],
    sources: [
      {
        id: "bs1",
        space_id: "s1",
        source_kind: "recording",
        source_id: "r1",
        source_title: "Parent call notes",
        created_at: null,
      },
    ],
    engine_profiles: ["obsidian", "gbrain", "mempalace"],
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

describe("BrainPanel (Live Mirror)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetBrainMirror.mockResolvedValue(projection());
    mockListBrainMaps.mockResolvedValue({ maps: [] });
    mockCreateBrainMap.mockResolvedValue(brainMap());
    mockRefreshBrainMap.mockResolvedValue(revision({ id: "rev-2", revision_index: 2 }));
    mockUpdateBrainMap.mockImplementation((_id, input) => Promise.resolve(brainMap({ ...input })));
    mockListEntities.mockResolvedValue(entities());
    mockListBrainSpaces.mockResolvedValue(spaces());
    mockGetBrainSpaceHome.mockResolvedValue(spaceHome());
    mockListBrainReviewPacks.mockResolvedValue(reviewPacks());
    mockAddBrainSpaceMember.mockResolvedValue({ id: "m1", space_id: "s1", user_id: "u2", role: "viewer", status: "active" });
    mockAcceptBrainReviewPack.mockResolvedValue({});
    mockRejectBrainReviewPack.mockResolvedValue({});
    mockExportBrainSpace.mockResolvedValue({
      space: spaces().spaces[0],
      profile: "obsidian",
      files: [{ path: "Customer stage rules.md", markdown: "# x" }],
    });
  });

  it("opens on a live canvas with maps, pages, and curated knowledge demoted", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByTestId("brain-map-canvas")).toBeInTheDocument());

    expect(screen.getByRole("button", { name: "Create Lens" })).toBeInTheDocument();
    expect(await screen.findByText("Launch notes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pages" })).toBeInTheDocument();
    expect(screen.getByText("Pricing")).toBeInTheDocument();
    expect(screen.getByText("Curated knowledge · Sources")).toBeInTheDocument();
    expect(screen.queryByLabelText("Ask your Brain")).not.toBeInTheDocument();
  });

  it("creates a draft lens from the Brain surface", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Create Lens" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Create Lens" }));
    fireEvent.change(screen.getByLabelText("Lens prompt"), {
      target: { value: "Map hiring risks" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() =>
      expect(mockCreateBrainMap).toHaveBeenCalledWith({
        prompt: "Map hiring risks",
        origin: "brain",
      }),
    );
    await waitFor(() => expect(screen.getAllByText("Hiring map").length).toBeGreaterThan(0));
  });

  it("creates a real-scenario diagram from the live mirror templates", async () => {
    render(<BrainPanel />);
    const templates = await screen.findByRole("region", { name: "Focus diagrams" });

    fireEvent.click(within(templates).getByRole("button", { name: "Projects: owners, risks, next steps" }));

    await waitFor(() =>
      expect(mockCreateBrainMap).toHaveBeenCalledWith({
        prompt: "Map my active projects with owners, risks, decisions, and next steps",
        origin: "brain",
      }),
    );
  });

  it("refreshes and keeps a draft map", async () => {
    mockListBrainMaps.mockResolvedValue({ maps: [brainMap()] });
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Hiring map")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Hiring map/ }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(mockRefreshBrainMap).toHaveBeenCalledWith("map-1"));

    fireEvent.click(screen.getByRole("button", { name: "Keep" }));
    await waitFor(() => expect(mockUpdateBrainMap).toHaveBeenCalledWith("map-1", { status: "saved" }));
  });

  it("opens a requested map after loading maps", async () => {
    mockListBrainMaps.mockResolvedValue({ maps: [brainMap()] });

    render(<BrainPanel initialMapId="map-1" />);

    await waitFor(() =>
      expect(screen.getByText("Showing 3 of 12 sources and 8 of 24 nodes.")).toBeInTheDocument(),
    );
    expect(screen.getAllByText("Project state").length).toBeGreaterThan(0);
  });

  it("shows generated-map briefing with evidence and next actions", async () => {
    const onOpenSource = vi.fn();
    const onOpenWai = vi.fn();
    mockListBrainMaps.mockResolvedValue({ maps: [brainMap()] });

    render(<BrainPanel onOpenSource={onOpenSource} onOpenWai={onOpenWai} />);
    await waitFor(() => expect(screen.getByText("Hiring map")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Hiring map/ }));
    expect(screen.getByText("Showing 3 of 12 sources and 8 of 24 nodes.")).toBeInTheDocument();
    expect(screen.getByText("3/12")).toBeInTheDocument();
    expect(screen.getByText("8/24")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Launch notes material/i }));
    expect(onOpenSource).toHaveBeenCalledWith("item", "item-1");

    fireEvent.click(screen.getByRole("button", { name: "Ask Wai" }));
    expect(onOpenWai).toHaveBeenCalledWith({ spaceId: "s1", spaceName: "Wai School" });

    fireEvent.click(screen.getByRole("button", { name: "What are the active risks?" }));
    await waitFor(() =>
      expect(mockCreateBrainMap).toHaveBeenCalledWith({
        prompt: "What are the active risks?",
        origin: "brain",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: /Anna person/i }));
    expect(screen.getByTestId("wiki-stub")).toHaveTextContent("wiki:e1");
  });

  it("opens sources and living pages from the map", async () => {
    const onOpenSource = vi.fn();
    render(<BrainPanel onOpenSource={onOpenSource} />);
    await waitFor(() => expect(screen.getByText("Launch notes")).toBeInTheDocument());

    const flow = screen.getByTestId("flow");
    fireEvent.click(within(flow).getByRole("button", { name: "Launch notes" }));
    expect(onOpenSource).toHaveBeenCalledWith("item", "item-1");

    fireEvent.click(within(flow).getByRole("button", { name: "Anna" }));
    expect(screen.getByTestId("wiki-stub")).toHaveTextContent("wiki:e1");
  });

  it("opens evidence sources from scenario signal cards", async () => {
    const onOpenSource = vi.fn();
    const baseProjection = projection();
    mockGetBrainMirror.mockResolvedValue(
      projection({
        nodes: [
          ...baseProjection.nodes,
          {
            id: "signal:risk:budget",
            kind: "risk",
            title: "Risk",
            body: "Budget approval is not final.",
            lane: "risks",
            source_kind: "item",
            source_id: "item-1",
            citation_ids: ["item:item-1"],
            position: { x: 340, y: 180 },
          },
        ],
      }),
    );

    render(<BrainPanel onOpenSource={onOpenSource} />);
    await waitFor(() => expect(screen.getByText("Risk")).toBeInTheDocument());

    fireEvent.click(within(screen.getByTestId("flow")).getByRole("button", { name: "Risk" }));
    expect(onOpenSource).toHaveBeenCalledWith("item", "item-1");
  });

  it("keeps crowded maps readable with a focused canvas layout", async () => {
    mockGetBrainMirror.mockResolvedValue(crowdedProjection());

    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("10 on canvas · 15 more in Brain")).toBeInTheDocument());

    const flow = screen.getByTestId("flow");
    await waitFor(() => expect(within(flow).getAllByRole("button")).toHaveLength(10));
    expect(within(flow).getByRole("button", { name: "Source 1" })).toHaveAttribute("data-x", "-420");
    expect(within(flow).getByRole("button", { name: "Project focus" })).toHaveAttribute("data-x", "0");
    expect(within(flow).getByRole("button", { name: "Entity 1" })).toHaveAttribute("data-x", "420");
  });

  it("keeps review, export, and share inside the curated disclosure", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Bridge from Mik Personal")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(mockAcceptBrainReviewPack).toHaveBeenCalledWith("s1", "rp1"));
    expect(screen.queryByText("Bridge from Mik Personal")).not.toBeInTheDocument();

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

  it("shows an empty state when nothing has been saved yet", async () => {
    mockGetBrainMirror.mockResolvedValue(projection({ nodes: [], edges: [], citations: [] }));
    mockListEntities.mockResolvedValue([]);
    mockListBrainSpaces.mockResolvedValue(spaces({ spaces: [] }));
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Start with sources")).toBeInTheDocument());
  });

  it("shows an error with a working retry", async () => {
    mockGetBrainMirror.mockRejectedValueOnce(new Error("mirror boom"));
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("mirror boom")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Retry/i }));
    await waitFor(() => expect(screen.getByText("Launch notes")).toBeInTheDocument());
  });
});
