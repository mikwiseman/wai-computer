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
    version: 8,
    snap_to_grid: false,
    grid_size: 40,
    viewport: { x: 0, y: 0, zoom: 1 },
    node_positions: {},
    strokes: [],
    cards: [],
    shapes: [],
    frames: [],
    texts: [],
    sources: [],
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
          {
            id: "source:item:1",
            kind: "source",
            title: "Launch memo",
            body: "The launch memo says the board approved the launch.",
            lane: "sources",
            source_kind: "item",
            source_id: "1",
            citation_ids: ["item:1"],
            position: { x: -360, y: 120 },
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
        citations: [
          {
            id: "item:1",
            source_kind: "item",
            source_id: "1",
            title: "Launch memo",
            kind: "material",
            created_at: "2026-06-17T09:00:00Z",
          },
        ],
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
            version: 8,
            node_positions: expect.objectContaining({
              "signal:decision:1": expect.objectContaining({ x: 380, y: -160 }),
            }),
          }),
        },
      ),
    );
  });

  it("pins cited sources as durable board blocks", async () => {
    render(<SchemesPanel />);

    await screen.findByTestId("schemes-panel");
    fireEvent.click(screen.getByRole("button", { name: "Pin sources" }));

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            version: 8,
            sources: [
              expect.objectContaining({
                id: "source-block:item:1",
                source_kind: "item",
                source_id: "1",
                citation_id: "item:1",
                title: "Launch memo",
                subtitle: "material / 2026-06-17",
                excerpt: "The launch memo says the board approved the launch.",
              }),
            ],
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

  it("persists snap settings and places new objects on the grid", async () => {
    const { container } = render(<SchemesPanel />);

    await screen.findByTestId("schemes-panel");
    fireEvent.click(screen.getByRole("checkbox", { name: "Snap to grid" }));

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            version: 8,
            snap_to_grid: true,
            grid_size: 40,
          }),
        },
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Sticky" }));
    const viewport = container.querySelector(".scheme-board__viewport");
    expect(viewport).not.toBeNull();

    fireEvent.pointerDown(viewport as Element, { pointerId: 1, clientX: 127, clientY: 166, button: 0 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenLastCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            snap_to_grid: true,
            grid_size: 40,
            cards: [
              expect.objectContaining({
                id: "card:test-id-1",
                x: 0,
                y: 80,
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
    fireEvent.click(screen.getByRole("button", { name: "Pen" }));
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
                kind: "pen",
                color: "#111827",
                width: 3,
                opacity: 1,
                points: expect.arrayContaining([
                  expect.objectContaining({ x: 20, y: 30, pressure: 1 }),
                  expect.objectContaining({ x: 48, y: 66, pressure: 1 }),
                ]),
              }),
            ],
          }),
        },
      ),
    );
  });

  it("persists highlighter strokes and erases unlocked strokes by path", async () => {
    const { container } = render(<SchemesPanel />);

    await screen.findByTestId("schemes-panel");
    fireEvent.click(screen.getByRole("button", { name: "Highlight" }));
    const viewport = container.querySelector(".scheme-board__viewport");
    expect(viewport).not.toBeNull();

    fireEvent.pointerDown(viewport as Element, { pointerId: 1, clientX: 22, clientY: 32, button: 0 });
    fireEvent.pointerMove(viewport as Element, { pointerId: 1, clientX: 80, clientY: 32, pressure: 0.6 });
    fireEvent.pointerUp(viewport as Element, { pointerId: 1, clientX: 80, clientY: 32 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenLastCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            strokes: [
              expect.objectContaining({
                id: "stroke:test-id-1",
                kind: "highlighter",
                color: "#facc15",
                width: 14,
                opacity: 0.35,
                points: expect.arrayContaining([
                  expect.objectContaining({ x: 80, y: 32, pressure: expect.any(Number) }),
                ]),
              }),
            ],
          }),
        },
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Erase" }));
    fireEvent.pointerDown(viewport as Element, { pointerId: 2, clientX: 50, clientY: 32, button: 0 });
    fireEvent.pointerUp(viewport as Element, { pointerId: 2, clientX: 50, clientY: 32 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenLastCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            strokes: [],
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
            locked: false,
            z_index: 10,
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

  it("resizes selected board objects from corner handles", async () => {
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
            locked: false,
            z_index: 10,
          },
        ],
      }),
    });
    mockListSchemes.mockResolvedValue({ schemes: [initial] });
    mockGetScheme.mockResolvedValue(initial);

    const { container } = render(<SchemesPanel />);

    const note = await screen.findByLabelText("Sticky note");
    const viewport = container.querySelector(".scheme-board__viewport");
    expect(viewport).not.toBeNull();

    fireEvent.pointerDown(note.parentElement as Element, { pointerId: 1, clientX: 260, clientY: 210, button: 0 });
    fireEvent.pointerUp(viewport as Element, { pointerId: 1, clientX: 260, clientY: 210 });

    const southeastHandle = container.querySelector(
      '[data-scheme-resize-item="card-existing"][data-scheme-resize-handle="se"]',
    );
    expect(southeastHandle).not.toBeNull();

    fireEvent.pointerDown(southeastHandle as Element, { pointerId: 2, clientX: 260, clientY: 210, button: 0 });
    fireEvent.pointerMove(viewport as Element, { pointerId: 2, clientX: 340, clientY: 250 });
    fireEvent.pointerUp(viewport as Element, { pointerId: 2, clientX: 340, clientY: 250 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [
              expect.objectContaining({
                id: "card-existing",
                x: 40,
                y: 60,
                width: 300,
                height: 190,
              }),
            ],
          }),
        },
      ),
    );
  });

  it("arranges a selected board object to the front and back", async () => {
    const initial = scheme({
      layout: layout({
        cards: [
          {
            id: "card-bottom",
            x: 40,
            y: 60,
            width: 220,
            height: 150,
            text: "Bottom note",
            color: "#f7d774",
            locked: false,
            z_index: 10,
          },
          {
            id: "card-top",
            x: 70,
            y: 90,
            width: 220,
            height: 150,
            text: "Top note",
            color: "#f7d774",
            locked: false,
            z_index: 20,
          },
        ],
      }),
    });
    mockListSchemes.mockResolvedValue({ schemes: [initial] });
    mockGetScheme.mockResolvedValue(initial);

    render(<SchemesPanel />);

    const notes = await screen.findAllByLabelText("Sticky note");
    fireEvent.pointerDown(notes[0].parentElement as Element, { pointerId: 1, clientX: 0, clientY: 0, button: 0 });
    fireEvent.click(screen.getByRole("button", { name: "Front" }));

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [
              expect.objectContaining({ id: "card-bottom", z_index: 21 }),
              expect.objectContaining({ id: "card-top", z_index: 20 }),
            ],
          }),
        },
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Back" }));

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [
              expect.objectContaining({ id: "card-bottom", z_index: 19 }),
              expect.objectContaining({ id: "card-top", z_index: 20 }),
            ],
          }),
        },
      ),
    );
  });

  it("marquee-selects and moves multiple board objects together", async () => {
    const initial = scheme({
      layout: layout({
        cards: [
          {
            id: "card-a",
            x: 40,
            y: 60,
            width: 220,
            height: 150,
            text: "First note",
            color: "#f7d774",
            locked: false,
            z_index: 10,
          },
          {
            id: "card-b",
            x: 260,
            y: 120,
            width: 220,
            height: 150,
            text: "Second note",
            color: "#f7d774",
            locked: false,
            z_index: 20,
          },
        ],
        connectors: [
          {
            id: "connector-a",
            source_id: "card-a",
            target_id: "card-b",
            points: [],
            label: null,
            color: "#475569",
            locked: false,
            z_index: 30,
          },
        ],
      }),
    });
    mockListSchemes.mockResolvedValue({ schemes: [initial] });
    mockGetScheme.mockResolvedValue(initial);

    const { container } = render(<SchemesPanel />);

    await screen.findByText("First note");
    const viewport = container.querySelector(".scheme-board__viewport");
    expect(viewport).not.toBeNull();

    fireEvent.pointerDown(viewport as Element, { pointerId: 1, clientX: 0, clientY: 0, button: 0 });
    fireEvent.pointerMove(viewport as Element, { pointerId: 1, clientX: 520, clientY: 320 });
    fireEvent.pointerUp(viewport as Element, { pointerId: 1, clientX: 520, clientY: 320 });
    expect(container.querySelector(".scheme-board__connector--selected")).not.toBeNull();

    const notes = screen.getAllByLabelText("Sticky note");
    fireEvent.pointerDown(notes[0].parentElement as Element, { pointerId: 2, clientX: 40, clientY: 60, button: 0 });
    fireEvent.pointerMove(viewport as Element, { pointerId: 2, clientX: 90, clientY: 90 });
    fireEvent.pointerUp(viewport as Element, { pointerId: 2, clientX: 90, clientY: 90 });

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [
              expect.objectContaining({ id: "card-a", x: 90, y: 90 }),
              expect.objectContaining({ id: "card-b", x: 310, y: 150 }),
            ],
          }),
        },
      ),
    );
  });

  it("lasso-selects objects by drawn containment and supports select-all", async () => {
    const initial = scheme({
      layout: layout({
        cards: [
          {
            id: "card-a",
            x: 40,
            y: 60,
            width: 220,
            height: 150,
            text: "Inside note",
            color: "#f7d774",
            locked: false,
            z_index: 10,
          },
          {
            id: "card-b",
            x: 360,
            y: 60,
            width: 220,
            height: 150,
            text: "Outside note",
            color: "#f7d774",
            locked: false,
            z_index: 20,
          },
        ],
      }),
    });
    mockListSchemes.mockResolvedValue({ schemes: [initial] });
    mockGetScheme.mockResolvedValue(initial);

    const { container } = render(<SchemesPanel />);

    await screen.findByText("Inside note");
    const viewport = container.querySelector(".scheme-board__viewport");
    expect(viewport).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Lasso" }));
    fireEvent.pointerDown(viewport as Element, { pointerId: 1, clientX: 20, clientY: 40, button: 0 });
    fireEvent.pointerMove(viewport as Element, { pointerId: 1, clientX: 300, clientY: 40 });
    fireEvent.pointerMove(viewport as Element, { pointerId: 1, clientX: 300, clientY: 240 });
    fireEvent.pointerMove(viewport as Element, { pointerId: 1, clientX: 20, clientY: 240 });
    fireEvent.pointerMove(viewport as Element, { pointerId: 1, clientX: 20, clientY: 40 });
    fireEvent.pointerUp(viewport as Element, { pointerId: 1, clientX: 20, clientY: 40 });

    expect(container.querySelectorAll(".scheme-sticky--selected")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [
              expect.objectContaining({ id: "card-a" }),
              expect.objectContaining({ id: "card-b" }),
              expect.objectContaining({
                id: "card:test-id-1",
                x: 72,
                y: 92,
                text: "Inside note",
              }),
            ],
          }),
        },
      ),
    );

    fireEvent.keyDown(viewport as Element, { key: "a", code: "KeyA", metaKey: true });
    expect(container.querySelectorAll(".scheme-sticky--selected")).toHaveLength(3);
  });

  it("locks and unlocks a selected board object", async () => {
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
            locked: false,
            z_index: 10,
          },
        ],
      }),
    });
    mockListSchemes.mockResolvedValue({ schemes: [initial] });
    mockGetScheme.mockResolvedValue(initial);

    render(<SchemesPanel />);

    const note = await screen.findByLabelText("Sticky note");
    fireEvent.pointerDown(note.parentElement as Element, { pointerId: 1, clientX: 0, clientY: 0, button: 0 });
    fireEvent.click(screen.getByRole("button", { name: "Lock" }));

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [expect.objectContaining({ id: "card-existing", locked: true })],
          }),
        },
      ),
    );
    expect(screen.getByRole("button", { name: "Duplicate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));

    await waitFor(() =>
      expect(mockUpdateScheme).toHaveBeenCalledWith(
        "scheme-1",
        {
          layout: expect.objectContaining({
            cards: [expect.objectContaining({ id: "card-existing", locked: false })],
          }),
        },
      ),
    );
  });
});
