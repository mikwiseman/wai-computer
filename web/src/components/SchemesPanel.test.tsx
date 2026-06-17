import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SchemesPanel } from "./SchemesPanel";
import type { Scheme, SchemeCanvasLayout } from "@/lib/types";

const mockCreateScheme = vi.fn();
const mockGetScheme = vi.fn();
const mockListSchemes = vi.fn();
const mockRefreshScheme = vi.fn();
const mockUpdateScheme = vi.fn();

vi.mock("@/lib/api", () => ({
  createScheme: (...a: unknown[]) => mockCreateScheme(...a),
  getScheme: (...a: unknown[]) => mockGetScheme(...a),
  listSchemes: (...a: unknown[]) => mockListSchemes(...a),
  refreshScheme: (...a: unknown[]) => mockRefreshScheme(...a),
  updateScheme: (...a: unknown[]) => mockUpdateScheme(...a),
}));

function layout(overrides: Partial<SchemeCanvasLayout> = {}): SchemeCanvasLayout {
  return {
    version: 3,
    viewport: { x: 0, y: 0, zoom: 1 },
    node_positions: {},
    strokes: [],
    cards: [],
    shapes: [],
    frames: [],
    texts: [],
    connectors: [],
    ...overrides,
  };
}

function scheme(overrides: Partial<Scheme> = {}): Scheme {
  return {
    id: "scheme-1",
    space_id: null,
    title: "Launch map",
    prompt: "Map launch decisions",
    scheme_type: "decision",
    origin: "brain",
    status: "draft",
    source_scope: null,
    layout: layout(),
    current_revision_id: "rev-1",
    created_at: "2026-06-17T10:00:00Z",
    updated_at: "2026-06-17T10:00:00Z",
    current_revision: {
      id: "rev-1",
      scheme_id: "scheme-1",
      revision_index: 1,
      source_fingerprint: "abc",
      source_count: 1,
      freshness: {},
      diff: { changed: true },
      citations: [],
      compiled_at: "2026-06-17T10:00:00Z",
      created_at: "2026-06-17T10:00:00Z",
      projection: {
        version: 1,
        scheme_type: "decision",
        title: "Launch map",
        prompt: "Map launch decisions",
        summary: "Decision from 1 source.",
        nodes: [
          {
            id: "lens:root",
            kind: "lens",
            title: "Launch map",
            body: "Map launch decisions",
            lane: "center",
            citation_ids: [],
            position: { x: 0, y: 0 },
          },
          {
            id: "signal:decision:1",
            kind: "decision",
            title: "Decision",
            body: "Board approved the launch.",
            lane: "decisions",
            citation_ids: ["item:1"],
            position: { x: 320, y: -180 },
          },
        ],
        edges: [
          {
            id: "edge:root:decision",
            source: "lens:root",
            target: "signal:decision:1",
            kind: "decision",
            label: "Decision",
            citation_ids: ["item:1"],
          },
        ],
        stats: { total_source_count: 1 },
        briefing: null,
        citations: [],
        freshness: {},
      },
    },
    ...overrides,
  };
}

describe("SchemesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    let idCounter = 0;
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn(() => `test-id-${++idCounter}`),
    });
    mockListSchemes.mockResolvedValue({ schemes: [scheme()] });
    mockGetScheme.mockResolvedValue(scheme());
    mockCreateScheme.mockResolvedValue(scheme({ id: "scheme-new", title: "New map" }));
    mockRefreshScheme.mockResolvedValue(scheme().current_revision);
    mockUpdateScheme.mockImplementation((_id: string, input: { layout?: SchemeCanvasLayout }) =>
      Promise.resolve(scheme({ layout: input.layout ?? layout() })),
    );
  });

  it("loads schemes and renders the selected infinite board nodes", async () => {
    render(<SchemesPanel />);

    await waitFor(() => expect(mockListSchemes).toHaveBeenCalled());
    await screen.findByTestId("schemes-panel");
    expect(screen.getAllByText("Launch map").length).toBeGreaterThan(0);
    expect(screen.getByText("Board approved the launch.")).toBeInTheDocument();
    expect(screen.getAllByText("1 source").length).toBeGreaterThan(0);
  });

  it("creates a new scheme from a prompt", async () => {
    render(<SchemesPanel />);

    const input = await screen.findByPlaceholderText("Map a project, decision, timeline, or open question");
    fireEvent.change(input, { target: { value: "Map Product Radar launch" } });
    fireEvent.click(screen.getByRole("button", { name: "Create scheme" }));

    await waitFor(() =>
      expect(mockCreateScheme).toHaveBeenCalledWith({ prompt: "Map Product Radar launch" }),
    );
  });

  it("saves node positions when a board card is dragged", async () => {
    render(<SchemesPanel />);

    const node = await screen.findByRole("button", { name: /Decision Board approved the launch/i });
    fireEvent.pointerDown(node, { pointerId: 1, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(node, { pointerId: 1, clientX: 70, clientY: 30 });
    fireEvent.pointerUp(node, { pointerId: 1, clientX: 70, clientY: 30 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            version: 3,
            node_positions: expect.objectContaining({
              "signal:decision:1": expect.objectContaining({ x: 380, y: -160 }),
            }),
          }),
        },
      ),
    );
  });

  it("adds a sticky note to the infinite board", async () => {
    const { container } = render(<SchemesPanel />);

    await screen.findByTestId("schemes-panel");
    fireEvent.click(screen.getByRole("button", { name: "Sticky" }));
    const viewport = container.querySelector(".scheme-board__viewport");
    expect(viewport).not.toBeNull();

    fireEvent.pointerDown(viewport as Element, { pointerId: 1, clientX: 120, clientY: 160, button: 0 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [
              expect.objectContaining({
                id: "card:test-id-1",
                text: "Note",
              }),
            ],
          }),
        },
      ),
    );
  });

  it("draws a persisted freehand stroke", async () => {
    const { container } = render(<SchemesPanel />);

    await screen.findByTestId("schemes-panel");
    fireEvent.click(screen.getByRole("button", { name: "Draw" }));
    const viewport = container.querySelector(".scheme-board__viewport");
    expect(viewport).not.toBeNull();

    fireEvent.pointerDown(viewport as Element, { pointerId: 1, clientX: 20, clientY: 30, button: 0 });
    fireEvent.pointerMove(viewport as Element, { pointerId: 1, clientX: 48, clientY: 66 });
    fireEvent.pointerUp(viewport as Element, { pointerId: 1, clientX: 48, clientY: 66 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            strokes: [
              expect.objectContaining({
                id: "stroke:test-id-1",
                points: expect.arrayContaining([
                  expect.objectContaining({ x: 20, y: 30 }),
                  expect.objectContaining({ x: 48, y: 66 }),
                ]),
              }),
            ],
          }),
        },
      ),
    );
  });

  it("adds a frame for organizing the board", async () => {
    const { container } = render(<SchemesPanel />);

    await screen.findByTestId("schemes-panel");
    fireEvent.click(screen.getByRole("button", { name: "Frame" }));
    const viewport = container.querySelector(".scheme-board__viewport");
    expect(viewport).not.toBeNull();

    fireEvent.pointerDown(viewport as Element, { pointerId: 1, clientX: 240, clientY: 260, button: 0 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            frames: [
              expect.objectContaining({
                id: "frame:test-id-1",
                title: "Frame",
              }),
            ],
          }),
        },
      ),
    );
  });

  it("adds editable canvas text", async () => {
    const { container } = render(<SchemesPanel />);

    await screen.findByTestId("schemes-panel");
    fireEvent.click(screen.getByRole("button", { name: "Text" }));
    const viewport = container.querySelector(".scheme-board__viewport");
    expect(viewport).not.toBeNull();

    fireEvent.pointerDown(viewport as Element, { pointerId: 1, clientX: 280, clientY: 300, button: 0 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            texts: [
              expect.objectContaining({
                id: "text:test-id-1",
                text: "Text",
              }),
            ],
          }),
        },
      ),
    );
  });

  it("creates a connector between two board objects", async () => {
    render(<SchemesPanel />);

    await screen.findByTestId("schemes-panel");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const root = screen.getByRole("button", { name: /Launch map Map launch decisions/i });
    const decision = screen.getByRole("button", { name: /Decision Board approved the launch/i });

    fireEvent.pointerDown(root, { pointerId: 1, clientX: 0, clientY: 0, button: 0 });
    fireEvent.pointerDown(decision, { pointerId: 2, clientX: 0, clientY: 0, button: 0 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            connectors: [
              expect.objectContaining({
                id: "connector:test-id-1",
                source_id: "lens:root",
                target_id: "signal:decision:1",
              }),
            ],
          }),
        },
      ),
    );
  });

  it("undoes and redoes a board mutation", async () => {
    const { container } = render(<SchemesPanel />);

    await screen.findByTestId("schemes-panel");
    fireEvent.click(screen.getByRole("button", { name: "Sticky" }));
    const viewport = container.querySelector(".scheme-board__viewport");
    expect(viewport).not.toBeNull();

    fireEvent.pointerDown(viewport as Element, { pointerId: 1, clientX: 120, clientY: 160, button: 0 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [expect.objectContaining({ id: "card:test-id-1" })],
          }),
        },
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [],
          }),
        },
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Redo" }));

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [expect.objectContaining({ id: "card:test-id-1" })],
          }),
        },
      ),
    );
  });

  it("duplicates a selected board object", async () => {
    const initial = scheme({
      layout: layout({
        cards: [
          {
            id: "card-existing",
            x: 40,
            y: 60,
            width: 220,
            height: 150,
            text: "Existing note",
            color: "#f7d774",
          },
        ],
      }),
    });
    mockListSchemes.mockResolvedValue({ schemes: [initial] });
    mockGetScheme.mockResolvedValue(initial);

    render(<SchemesPanel />);

    const note = await screen.findByLabelText("Sticky note");
    fireEvent.pointerDown(note.parentElement as Element, { pointerId: 1, clientX: 0, clientY: 0, button: 0 });
    fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [
              expect.objectContaining({ id: "card-existing" }),
              expect.objectContaining({
                id: "card:test-id-1",
                x: 72,
                y: 92,
                text: "Existing note",
              }),
            ],
          }),
        },
      ),
    );
  });
});
