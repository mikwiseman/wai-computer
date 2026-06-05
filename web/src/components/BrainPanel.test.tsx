import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrainPanel } from "./BrainPanel";

const mockAskBrain = vi.fn();
const mockListEntities = vi.fn();
const mockListBrainSpaces = vi.fn();
const mockGetBrainSpaceHome = vi.fn();
const mockListBrainReviewPacks = vi.fn();
const mockAddBrainSpaceMember = vi.fn();
const mockAcceptBrainReviewPack = vi.fn();
const mockRejectBrainReviewPack = vi.fn();
const mockExportBrainSpace = vi.fn();

vi.mock("@/lib/api", () => ({
  acceptBrainReviewPack: (...a: unknown[]) => mockAcceptBrainReviewPack(...a),
  addBrainSpaceMember: (...a: unknown[]) => mockAddBrainSpaceMember(...a),
  askBrain: (...a: unknown[]) => mockAskBrain(...a),
  exportBrainSpace: (...a: unknown[]) => mockExportBrainSpace(...a),
  getBrainSpaceHome: (...a: unknown[]) => mockGetBrainSpaceHome(...a),
  listBrainReviewPacks: (...a: unknown[]) => mockListBrainReviewPacks(...a),
  listBrainSpaces: (...a: unknown[]) => mockListBrainSpaces(...a),
  listEntities: (...a: unknown[]) => mockListEntities(...a),
  rejectBrainReviewPack: (...a: unknown[]) => mockRejectBrainReviewPack(...a),
}));

vi.mock("@/components/EntityWikiView", () => ({
  EntityWikiView: ({ entityId }: { entityId: string }) => (
    <div data-testid="wiki-stub">wiki:{entityId}</div>
  ),
}));

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

function answer(overrides = {}) {
  return {
    answer: "Pricing needs legal sign-off [1].",
    citations: [
      { id: "seg1", source_kind: "recording", source_id: "r1", title: "Q3 sync", start_ms: 1000 },
    ],
    gaps: ["No deadline was mentioned."],
    freshness: { newest_source_at: "2026-01-01T00:00:00Z", weeks_since: 8, stale: true },
    ...overrides,
  };
}

describe("BrainPanel (unified surface)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListEntities.mockResolvedValue(entities());
    mockListBrainSpaces.mockResolvedValue(spaces());
    mockGetBrainSpaceHome.mockResolvedValue(spaceHome());
    mockListBrainReviewPacks.mockResolvedValue(reviewPacks());
    mockAskBrain.mockResolvedValue(answer());
    mockAddBrainSpaceMember.mockResolvedValue({ id: "m1", space_id: "s1", user_id: "u2", role: "viewer", status: "active" });
    mockAcceptBrainReviewPack.mockResolvedValue({});
    mockRejectBrainReviewPack.mockResolvedValue({});
    mockExportBrainSpace.mockResolvedValue({
      space: spaces().spaces[0],
      profile: "obsidian",
      files: [{ path: "Customer stage rules.md", markdown: "# x" }],
    });
  });

  it("shows one Ask box + a Pages list, with curated knowledge demoted", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());

    expect(screen.getByLabelText("Ask your Brain")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pages" })).toBeInTheDocument();
    expect(screen.getByText("Pricing")).toBeInTheDocument();
    expect(screen.getByText("Curated knowledge · Sources")).toBeInTheDocument();
    // No old two-tab chrome.
    expect(screen.queryByRole("tab", { name: "Home" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Knowledge" })).not.toBeInTheDocument();
  });

  it("answers a question with citations, gaps, and a staleness heads-up", async () => {
    const onOpenSource = vi.fn();
    render(<BrainPanel onOpenSource={onOpenSource} />);
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Ask your Brain"), {
      target: { value: "what's open with Alice?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(mockAskBrain).toHaveBeenCalledWith("what's open with Alice?"));
    expect(await screen.findByText("Pricing needs legal sign-off [1].")).toBeInTheDocument();
    expect(screen.getByText("No deadline was mentioned.")).toBeInTheDocument();
    expect(screen.getByText(/nothing has been added about this in 8 weeks/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Q3 sync/i }));
    expect(onOpenSource).toHaveBeenCalledWith("recording", "r1");
  });

  it("filters Pages by type and opens a living page", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "People" }));
    expect(screen.getByText("Anna")).toBeInTheDocument();
    expect(screen.queryByText("Pricing")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Anna/i }));
    expect(screen.getByTestId("wiki-stub")).toHaveTextContent("wiki:e1");
  });

  it("keeps review + export + share inside the curated disclosure", async () => {
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
    mockListEntities.mockResolvedValue([]);
    mockListBrainSpaces.mockResolvedValue(spaces({ spaces: [] }));
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Start with sources")).toBeInTheDocument());
  });

  it("shows an error with a working retry", async () => {
    mockListEntities.mockRejectedValueOnce(new Error("entities boom"));
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("entities boom")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Retry/i }));
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
  });
});
