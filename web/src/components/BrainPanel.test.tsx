import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrainPanel } from "./BrainPanel";

const mockListEntities = vi.fn();

vi.mock("@/lib/api", () => ({
  listEntities: (...a: unknown[]) => mockListEntities(...a),
}));

// EntityWikiView owns its own data + rendering (tested separately); stub it to a
// marker plus an Ask-Wai trigger so we can assert the deep-link prop is wired.
vi.mock("@/components/EntityWikiView", () => ({
  EntityWikiView: ({
    entityId,
    onAskWai,
  }: {
    entityId: string;
    onAskWai?: (id: string, name: string) => void;
  }) => (
    <div data-testid="wiki-stub">
      wiki:{entityId}
      <button type="button" onClick={() => onAskWai?.(entityId, "stub")}>
        ask-wai-stub
      </button>
    </div>
  ),
}));

function entities() {
  return [
    {
      id: "e1",
      type: "person",
      name: "Anna",
      metadata: null,
      created_at: "",
      mention_count: 2,
      source_count: 2,
      overview_snippet: "Leads the Atlas launch.",
    },
    {
      id: "e2",
      type: "topic",
      name: "Pricing",
      metadata: null,
      created_at: "",
      mention_count: 1,
      source_count: 1,
    },
  ];
}

describe("BrainPanel (wiki)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListEntities.mockResolvedValue(entities());
  });

  it("renders the Pages index (no cockpit) and opens a dossier on click", async () => {
    render(<BrainPanel />);
    expect(await screen.findByText("Anna")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pages" })).toBeInTheDocument();
    expect(screen.getByText("Pricing")).toBeInTheDocument();
    // the compiled overview snippet is the card subtitle
    expect(screen.getByText("Leads the Atlas launch.")).toBeInTheDocument();
    // the cockpit is gone
    expect(screen.queryByRole("region", { name: "Ask Brain" })).not.toBeInTheDocument();
    expect(screen.queryByText("Create Lens")).not.toBeInTheDocument();
    expect(screen.queryByText("Source mirror")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Anna"));
    expect(screen.getByTestId("wiki-stub")).toHaveTextContent("wiki:e1");
  });

  it("filters pages by type", async () => {
    render(<BrainPanel />);
    await screen.findByText("Anna");

    fireEvent.click(screen.getByRole("tab", { name: "People" }));
    expect(screen.getByText("Anna")).toBeInTheDocument();
    expect(screen.queryByText("Pricing")).not.toBeInTheDocument();
  });

  it("searches pages by name", async () => {
    render(<BrainPanel />);
    await screen.findByText("Anna");

    fireEvent.change(screen.getByLabelText("Search pages"), { target: { value: "pric" } });
    expect(screen.queryByText("Anna")).not.toBeInTheDocument();
    expect(screen.getByText("Pricing")).toBeInTheDocument();
  });

  it("deep-links 'Ask Wai about X' from a dossier to an entity-scoped chat", async () => {
    const onAskWaiAboutEntity = vi.fn();
    render(<BrainPanel onAskWaiAboutEntity={onAskWaiAboutEntity} />);
    fireEvent.click(await screen.findByText("Anna"));

    fireEvent.click(screen.getByRole("button", { name: "ask-wai-stub" }));
    expect(onAskWaiAboutEntity).toHaveBeenCalledWith("e1", "stub");
  });

  it("shows an empty state when there are no pages", async () => {
    mockListEntities.mockResolvedValue([]);
    const onOpenInbox = vi.fn();
    render(<BrainPanel onOpenInbox={onOpenInbox} />);

    expect(
      await screen.findByText(
        "Pages appear as Wai finds people, projects, and topics in your sources.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Inbox" }));
    expect(onOpenInbox).toHaveBeenCalled();
  });

  it("shows an error with a working retry", async () => {
    mockListEntities.mockRejectedValueOnce(new Error("entities boom"));
    render(<BrainPanel />);
    expect(await screen.findByText("entities boom")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Anna")).toBeInTheDocument();
  });
});
