import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrainPanel } from "./BrainPanel";

const mockGetBrainGraph = vi.fn();

vi.mock("@/lib/api", () => ({
  getBrainGraph: (...a: unknown[]) => mockGetBrainGraph(...a),
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
    stats: { entities: 3, people: 1, topics: 2, items: 1, recordings: 0, mentions: 9 },
    ...overrides,
  };
}

describe("BrainPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetBrainGraph.mockResolvedValue(graph());
  });

  it("renders categorized entities sorted by degree (sources excluded)", async () => {
    render(<BrainPanel />);
    await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
    expect(screen.getByText("People")).toBeInTheDocument();
    expect(screen.getByText("Topics")).toBeInTheDocument();

    const topics = screen.getByText("Topics").closest("section") as HTMLElement;
    const chips = topics.querySelectorAll(".brain-panel__chip span");
    expect(chips[0].textContent).toBe("GPU"); // degree 5 first
    expect(chips[1].textContent).toBe("Pricing"); // degree 1

    expect(screen.queryByText("Solar Note")).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no entities", async () => {
    mockGetBrainGraph.mockResolvedValue(graph({ nodes: [], stats: { entities: 0 } }));
    render(<BrainPanel />);
    await waitFor(() =>
      expect(screen.getByText(/Your brain is empty/i)).toBeInTheDocument(),
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
