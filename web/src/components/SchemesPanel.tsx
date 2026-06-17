"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent, WheelEvent } from "react";
import {
  createScheme,
  getScheme,
  listSchemes,
  refreshScheme,
  updateScheme,
} from "@/lib/api";
import type {
  Scheme,
  SchemeCanvasCard,
  SchemeCanvasFrame,
  SchemeCanvasLayout,
  SchemeCanvasShape,
  SchemeConnector,
  SchemeNode,
  SchemePosition,
  SchemeShapeKind,
  SchemeStroke,
  SchemeTextBlock,
  SchemeViewport,
} from "@/lib/types";

type Locale = "en" | "ru";
type Tool =
  | "select"
  | "pan"
  | "draw"
  | "sticky"
  | "text"
  | "rectangle"
  | "ellipse"
  | "frame"
  | "connector";
type BoardItemKind = "node" | "card" | "shape" | "frame" | "text";

interface SchemesPanelProps {
  locale?: Locale;
  onError?: (message: string) => void;
}

type DragState =
  | {
      type: "node";
      nodeId: string;
      start: SchemePosition;
      origin: SchemePosition;
    }
  | {
      type: "card";
      cardId: string;
      start: SchemePosition;
      origin: SchemePosition;
    }
  | {
      type: "shape";
      shapeId: string;
      start: SchemePosition;
      origin: SchemePosition;
    }
  | {
      type: "frame";
      frameId: string;
      start: SchemePosition;
      origin: SchemePosition;
    }
  | {
      type: "text";
      textId: string;
      start: SchemePosition;
      origin: SchemePosition;
    }
  | {
      type: "pan";
      startClientX: number;
      startClientY: number;
      origin: SchemeViewport;
    }
  | {
      type: "stroke";
      strokeId: string;
    };

interface BoardItemHandle {
  id: string;
  kind: BoardItemKind;
}

const SCHEME_LAYOUT_VERSION = 5 as const;
const DEFAULT_VIEWPORT: SchemeViewport = { x: 0, y: 0, zoom: 1 };
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2.8;
const NODE_WIDTH = 232;
const NODE_HEIGHT = 132;
const STICKY_WIDTH = 220;
const STICKY_HEIGHT = 150;
const SHAPE_WIDTH = 220;
const SHAPE_HEIGHT = 130;
const FRAME_WIDTH = 560;
const FRAME_HEIGHT = 360;
const TEXT_WIDTH = 260;
const TEXT_HEIGHT = 120;
const TOOLS: Array<{ id: Tool; label: string; ru: string }> = [
  { id: "select", label: "Select", ru: "Выбор" },
  { id: "pan", label: "Hand", ru: "Рука" },
  { id: "draw", label: "Draw", ru: "Рисовать" },
  { id: "sticky", label: "Sticky", ru: "Стикер" },
  { id: "text", label: "Text", ru: "Текст" },
  { id: "rectangle", label: "Box", ru: "Блок" },
  { id: "ellipse", label: "Oval", ru: "Овал" },
  { id: "frame", label: "Frame", ru: "Фрейм" },
  { id: "connector", label: "Connect", ru: "Связь" },
];

const COPY = {
  en: {
    title: "Schemes",
    subtitle: "Infinite boards for mapping evidence, decisions, drawings, and working structure.",
    promptPlaceholder: "Map a project, decision, timeline, or open question",
    create: "Create scheme",
    creating: "Creating...",
    refresh: "Refresh evidence",
    refreshing: "Refreshing...",
    undo: "Undo",
    redo: "Redo",
    duplicate: "Duplicate",
    lock: "Lock",
    unlock: "Unlock",
    bringFront: "Front",
    bringForward: "Forward",
    sendBackward: "Backward",
    sendBack: "Back",
    emptyTitle: "No schemes yet",
    emptyBody: "Create one from a prompt. Wai will build a cited board from your recordings, materials, and chats.",
    noSelection: "Select a scheme or create a new one.",
    noProjection: "No cited projection yet. You can still draw and structure the board.",
    reset: "Reset view",
    zoomIn: "Zoom in",
    zoomOut: "Zoom out",
    delete: "Delete",
    source: (count: number) => `${count} source${count === 1 ? "" : "s"}`,
    connectorHint: "Click a second object to connect it.",
    loading: "Loading...",
  },
  ru: {
    title: "Схемы",
    subtitle: "Бесконечные доски для фактов, решений, рисунков и рабочей структуры.",
    promptPlaceholder: "Собрать карту проекта, решения, таймлайна или вопроса",
    create: "Создать схему",
    creating: "Создаем...",
    refresh: "Обновить факты",
    refreshing: "Обновляем...",
    undo: "Отменить",
    redo: "Повторить",
    duplicate: "Дублировать",
    lock: "Заблокировать",
    unlock: "Разблокировать",
    bringFront: "Наверх",
    bringForward: "Вперед",
    sendBackward: "Назад",
    sendBack: "Вниз",
    emptyTitle: "Схем пока нет",
    emptyBody: "Создайте схему по запросу. Wai соберет доску с источниками из записей, материалов и чатов.",
    noSelection: "Выберите схему или создайте новую.",
    noProjection: "Проекции пока нет. На доске уже можно рисовать и собирать структуру.",
    reset: "Сбросить вид",
    zoomIn: "Приблизить",
    zoomOut: "Отдалить",
    delete: "Удалить",
    source: (count: number) => `${count} источн.`,
    connectorHint: "Нажмите второй объект, чтобы соединить.",
    loading: "Загрузка...",
  },
} as const;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function blankLayout(): SchemeCanvasLayout {
  return {
    version: SCHEME_LAYOUT_VERSION,
    viewport: { ...DEFAULT_VIEWPORT },
    node_positions: {},
    strokes: [],
    cards: [],
    shapes: [],
    frames: [],
    texts: [],
    connectors: [],
  };
}

type LayerAction = "front" | "forward" | "backward" | "back";
type LayerItem = { id: string; zIndex: number };

function normaliseLayoutLayers(layout: SchemeCanvasLayout): SchemeCanvasLayout {
  const existingIndexes = layoutLayerItems(layout)
    .map((item) => item.zIndex)
    .filter(Number.isFinite);
  let nextIndex = existingIndexes.length === 0 ? 1 : Math.max(...existingIndexes) + 1;
  const withIndex = <T extends { z_index: number }>(items: T[]) =>
    items.map((item) => ({
      ...item,
      z_index: Number.isFinite(item.z_index) ? item.z_index : nextIndex++,
    }));

  return {
    ...layout,
    connectors: withIndex(layout.connectors),
    strokes: withIndex(layout.strokes),
    shapes: withIndex(layout.shapes),
    frames: withIndex(layout.frames),
    texts: withIndex(layout.texts),
    cards: withIndex(layout.cards),
  };
}

function isPosition(value: unknown): value is SchemePosition {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { x?: unknown }).x === "number" &&
    typeof (value as { y?: unknown }).y === "number"
  );
}

function layoutForScheme(scheme: Scheme | null): SchemeCanvasLayout {
  const raw = scheme?.layout;
  if (!raw) return blankLayout();
  const maybeLegacy = raw as unknown as Record<string, unknown>;
  if (!("version" in maybeLegacy) && Object.values(maybeLegacy).every(isPosition)) {
    return { ...blankLayout(), node_positions: maybeLegacy as Record<string, SchemePosition> };
  }
  return normaliseLayoutLayers({
    ...blankLayout(),
    ...raw,
    version: SCHEME_LAYOUT_VERSION,
    viewport: { ...DEFAULT_VIEWPORT, ...(raw.viewport ?? {}) },
    node_positions: raw.node_positions ?? {},
    strokes: (raw.strokes ?? []).map((stroke) => ({ ...stroke, locked: stroke.locked ?? false, z_index: stroke.z_index ?? Number.NaN })),
    cards: (raw.cards ?? []).map((card) => ({ ...card, locked: card.locked ?? false, z_index: card.z_index ?? Number.NaN })),
    shapes: (raw.shapes ?? []).map((shape) => ({ ...shape, locked: shape.locked ?? false, z_index: shape.z_index ?? Number.NaN })),
    frames: (raw.frames ?? []).map((frame) => ({ ...frame, locked: frame.locked ?? false, z_index: frame.z_index ?? Number.NaN })),
    texts: (raw.texts ?? []).map((text) => ({ ...text, locked: text.locked ?? false, z_index: text.z_index ?? Number.NaN })),
    connectors: (raw.connectors ?? []).map((connector) => ({ ...connector, locked: connector.locked ?? false, z_index: connector.z_index ?? Number.NaN })),
  });
}

function nodePosition(node: SchemeNode, layout: SchemeCanvasLayout): SchemePosition {
  return layout.node_positions[node.id] ?? node.position;
}

function nodeKindLabel(kind: string): string {
  return kind.replaceAll("_", " ");
}

function createId(prefix: string): string {
  return `${prefix}:${crypto.randomUUID()}`;
}

function applyRevision(scheme: Scheme, revision: NonNullable<Scheme["current_revision"]>): Scheme {
  return {
    ...scheme,
    current_revision_id: revision.id,
    current_revision: revision,
  };
}

function itemCenter(
  itemId: string | null,
  nodes: SchemeNode[],
  layout: SchemeCanvasLayout,
): SchemePosition | null {
  if (!itemId) return null;
  const node = nodes.find((candidate) => candidate.id === itemId);
  if (node) {
    return { x: node.position.x + NODE_WIDTH / 2, y: node.position.y + NODE_HEIGHT / 2 };
  }
  const card = layout.cards.find((candidate) => candidate.id === itemId);
  if (card) {
    return { x: card.x + card.width / 2, y: card.y + card.height / 2 };
  }
  const shape = layout.shapes.find((candidate) => candidate.id === itemId);
  if (shape) {
    return { x: shape.x + shape.width / 2, y: shape.y + shape.height / 2 };
  }
  const frame = layout.frames.find((candidate) => candidate.id === itemId);
  if (frame) {
    return { x: frame.x + frame.width / 2, y: frame.y + frame.height / 2 };
  }
  const text = layout.texts.find((candidate) => candidate.id === itemId);
  if (text) {
    return { x: text.x + text.width / 2, y: text.y + text.height / 2 };
  }
  return null;
}

function isLayoutItemLocked(itemId: string | null, layout: SchemeCanvasLayout): boolean {
  if (!itemId) return false;
  return (
    layout.cards.some((candidate) => candidate.id === itemId && candidate.locked) ||
    layout.shapes.some((candidate) => candidate.id === itemId && candidate.locked) ||
    layout.frames.some((candidate) => candidate.id === itemId && candidate.locked) ||
    layout.texts.some((candidate) => candidate.id === itemId && candidate.locked) ||
    layout.strokes.some((candidate) => candidate.id === itemId && candidate.locked) ||
    layout.connectors.some((candidate) => candidate.id === itemId && candidate.locked)
  );
}

function canLockLayoutItem(itemId: string | null, layout: SchemeCanvasLayout): boolean {
  if (!itemId) return false;
  return (
    layout.cards.some((candidate) => candidate.id === itemId) ||
    layout.shapes.some((candidate) => candidate.id === itemId) ||
    layout.frames.some((candidate) => candidate.id === itemId) ||
    layout.texts.some((candidate) => candidate.id === itemId) ||
    layout.strokes.some((candidate) => candidate.id === itemId) ||
    layout.connectors.some((candidate) => candidate.id === itemId)
  );
}

function layoutLayerItems(layout: SchemeCanvasLayout): LayerItem[] {
  return [
    ...layout.connectors.map((connector) => ({ id: connector.id, zIndex: connector.z_index })),
    ...layout.strokes.map((stroke) => ({ id: stroke.id, zIndex: stroke.z_index })),
    ...layout.shapes.map((shape) => ({ id: shape.id, zIndex: shape.z_index })),
    ...layout.frames.map((frame) => ({ id: frame.id, zIndex: frame.z_index })),
    ...layout.texts.map((text) => ({ id: text.id, zIndex: text.z_index })),
    ...layout.cards.map((card) => ({ id: card.id, zIndex: card.z_index })),
  ];
}

function nextLayerIndex(layout: SchemeCanvasLayout): number {
  const indexes = layoutLayerItems(layout).map((item) => item.zIndex);
  return indexes.length === 0 ? 1 : Math.max(...indexes) + 1;
}

function layerZIndex(zIndex: number): number {
  return 10 + zIndex;
}

function setLayoutItemZIndex(layout: SchemeCanvasLayout, itemId: string, zIndex: number): SchemeCanvasLayout {
  return {
    ...layout,
    cards: layout.cards.map((card) => (card.id === itemId ? { ...card, z_index: zIndex } : card)),
    shapes: layout.shapes.map((shape) => (shape.id === itemId ? { ...shape, z_index: zIndex } : shape)),
    frames: layout.frames.map((frame) => (frame.id === itemId ? { ...frame, z_index: zIndex } : frame)),
    texts: layout.texts.map((text) => (text.id === itemId ? { ...text, z_index: zIndex } : text)),
    strokes: layout.strokes.map((stroke) => (stroke.id === itemId ? { ...stroke, z_index: zIndex } : stroke)),
    connectors: layout.connectors.map((connector) =>
      connector.id === itemId ? { ...connector, z_index: zIndex } : connector,
    ),
  };
}

function arrangeLayoutItem(layout: SchemeCanvasLayout, itemId: string, action: LayerAction): SchemeCanvasLayout {
  const normalised = normaliseLayoutLayers(layout);
  const items = layoutLayerItems(normalised).sort((a, b) => a.zIndex - b.zIndex);
  const currentIndex = items.findIndex((item) => item.id === itemId);
  if (currentIndex === -1) return layout;

  if (action === "front") {
    return setLayoutItemZIndex(normalised, itemId, items[items.length - 1].zIndex + 1);
  }
  if (action === "back") {
    return setLayoutItemZIndex(normalised, itemId, items[0].zIndex - 1);
  }

  const neighborIndex = action === "forward" ? currentIndex + 1 : currentIndex - 1;
  if (neighborIndex < 0 || neighborIndex >= items.length) return normalised;
  const current = items[currentIndex];
  const neighbor = items[neighborIndex];
  return setLayoutItemZIndex(
    setLayoutItemZIndex(normalised, current.id, neighbor.zIndex),
    neighbor.id,
    current.zIndex,
  );
}

function shapePath(shape: SchemeCanvasShape): string {
  if (shape.kind === "ellipse") {
    const rx = shape.width / 2;
    const ry = shape.height / 2;
    const cx = shape.x + rx;
    const cy = shape.y + ry;
    return [
      `M ${cx - rx} ${cy}`,
      `a ${rx} ${ry} 0 1 0 ${shape.width} 0`,
      `a ${rx} ${ry} 0 1 0 ${-shape.width} 0`,
    ].join(" ");
  }
  return `M ${shape.x} ${shape.y} h ${shape.width} v ${shape.height} h ${-shape.width} Z`;
}

function cloneLayout(layout: SchemeCanvasLayout): SchemeCanvasLayout {
  return {
    version: layout.version,
    viewport: { ...layout.viewport },
    node_positions: Object.fromEntries(
      Object.entries(layout.node_positions).map(([id, position]) => [id, { ...position }]),
    ),
    strokes: layout.strokes.map((stroke) => ({
      ...stroke,
      points: stroke.points.map((point) => ({ ...point })),
    })),
    cards: layout.cards.map((card) => ({ ...card })),
    shapes: layout.shapes.map((shape) => ({ ...shape })),
    frames: layout.frames.map((frame) => ({ ...frame })),
    texts: layout.texts.map((text) => ({ ...text })),
    connectors: layout.connectors.map((connector) => ({
      ...connector,
      points: connector.points.map((point) => ({ ...point })),
    })),
  };
}

function layoutFingerprint(layout: SchemeCanvasLayout): string {
  return JSON.stringify(layout);
}

export function SchemesPanel({ locale = "en", onError }: SchemesPanelProps) {
  const copy = COPY[locale];
  const [schemes, setSchemes] = useState<Scheme[]>([]);
  const [selected, setSelected] = useState<Scheme | null>(null);
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [layout, setLayout] = useState<SchemeCanvasLayout>(blankLayout);
  const [tool, setTool] = useState<Tool>("select");
  const [selectedItem, setSelectedItem] = useState<string | null>(null);
  const [pendingConnector, setPendingConnector] = useState<BoardItemHandle | null>(null);
  const [historyCounts, setHistoryCounts] = useState({ undo: 0, redo: 0 });
  const dragRef = useRef<DragState | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const selectedRef = useRef<Scheme | null>(null);
  const layoutRef = useRef<SchemeCanvasLayout>(layout);
  const wheelCommitRef = useRef<number | null>(null);
  const undoStackRef = useRef<SchemeCanvasLayout[]>([]);
  const redoStackRef = useRef<SchemeCanvasLayout[]>([]);
  const editingItemRef = useRef<string | null>(null);

  const selectedId = selected?.id ?? null;
  selectedRef.current = selected;
  layoutRef.current = layout;

  const reportError = useCallback(
    (err: unknown, defaultMessage: string) => {
      onError?.(err instanceof Error ? err.message : defaultMessage);
    },
    [onError],
  );

  const replaceScheme = useCallback((scheme: Scheme) => {
    setSelected(scheme);
    setLayout(layoutForScheme(scheme));
    setSchemes((current) => current.map((item) => (item.id === scheme.id ? scheme : item)));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await listSchemes();
      setSchemes(response.schemes);
      setSelected((current) => {
        if (current && response.schemes.some((scheme) => scheme.id === current.id)) {
          return response.schemes.find((scheme) => scheme.id === current.id) ?? current;
        }
        return response.schemes[0] ?? null;
      });
    } catch (err) {
      reportError(err, "Couldn't load schemes.");
    } finally {
      setLoading(false);
    }
  }, [reportError]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(
    () => () => {
      if (wheelCommitRef.current !== null) {
        window.clearTimeout(wheelCommitRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    setLayout(layoutForScheme(selectedRef.current));
    setSelectedItem(null);
    setPendingConnector(null);
    undoStackRef.current = [];
    redoStackRef.current = [];
    editingItemRef.current = null;
    setHistoryCounts({ undo: 0, redo: 0 });
  }, [selectedId]);

  const projection = selected?.current_revision?.projection ?? null;
  const positionedNodes = useMemo(() => {
    if (!projection) return [];
    return projection.nodes.map((node) => ({
      ...node,
      position: nodePosition(node, layout),
    }));
  }, [projection, layout]);
  const nodeById = useMemo(
    () => new Map(positionedNodes.map((node) => [node.id, node])),
    [positionedNodes],
  );
  const canDeleteSelected = useMemo(() => {
    if (!selectedItem) return false;
    if (isLayoutItemLocked(selectedItem, layout)) return false;
    return (
      layout.cards.some((card) => card.id === selectedItem) ||
      layout.shapes.some((shape) => shape.id === selectedItem) ||
      layout.frames.some((frame) => frame.id === selectedItem) ||
      layout.texts.some((text) => text.id === selectedItem) ||
      layout.strokes.some((stroke) => stroke.id === selectedItem) ||
      layout.connectors.some((connector) => connector.id === selectedItem)
    );
  }, [layout, selectedItem]);
  const canDuplicateSelected = useMemo(() => {
    if (!selectedItem) return false;
    if (isLayoutItemLocked(selectedItem, layout)) return false;
    return (
      layout.cards.some((card) => card.id === selectedItem) ||
      layout.shapes.some((shape) => shape.id === selectedItem) ||
      layout.frames.some((frame) => frame.id === selectedItem) ||
      layout.texts.some((text) => text.id === selectedItem) ||
      layout.strokes.some((stroke) => stroke.id === selectedItem)
    );
  }, [layout, selectedItem]);
  const canLockSelected = useMemo(
    () => canLockLayoutItem(selectedItem, layout),
    [layout, selectedItem],
  );
  const selectedItemLocked = useMemo(
    () => isLayoutItemLocked(selectedItem, layout),
    [layout, selectedItem],
  );
  const canArrangeSelected = useMemo(
    () => canLockLayoutItem(selectedItem, layout) && !isLayoutItemLocked(selectedItem, layout),
    [layout, selectedItem],
  );

  const commitLayout = useCallback(
    async (nextLayout: SchemeCanvasLayout) => {
      if (!selectedRef.current) return;
      try {
        const updated = await updateScheme(selectedRef.current.id, { layout: nextLayout });
        replaceScheme(updated);
      } catch (err) {
        reportError(err, "Couldn't save scheme board.");
      }
    },
    [replaceScheme, reportError],
  );

  const setLocalLayout = useCallback((updater: (current: SchemeCanvasLayout) => SchemeCanvasLayout) => {
    setLayout((current) => {
      const next = updater(current);
      layoutRef.current = next;
      return next;
    });
  }, []);

  const updateHistoryCounts = useCallback(() => {
    setHistoryCounts({
      undo: undoStackRef.current.length,
      redo: redoStackRef.current.length,
    });
  }, []);

  const pushUndoSnapshot = useCallback(
    (source: SchemeCanvasLayout = layoutRef.current) => {
      const snapshot = cloneLayout(source);
      const previous = undoStackRef.current[undoStackRef.current.length - 1];
      if (!previous || layoutFingerprint(previous) !== layoutFingerprint(snapshot)) {
        undoStackRef.current = [...undoStackRef.current.slice(-79), snapshot];
      }
      redoStackRef.current = [];
      updateHistoryCounts();
    },
    [updateHistoryCounts],
  );

  const restoreHistoryLayout = useCallback(
    (nextLayout: SchemeCanvasLayout) => {
      setSelectedItem(null);
      setPendingConnector(null);
      dragRef.current = null;
      editingItemRef.current = null;
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout],
  );

  const undoLayout = useCallback(() => {
    const previous = undoStackRef.current.pop();
    if (!previous) return;
    redoStackRef.current.push(cloneLayout(layoutRef.current));
    updateHistoryCounts();
    restoreHistoryLayout(previous);
  }, [restoreHistoryLayout, updateHistoryCounts]);

  const redoLayout = useCallback(() => {
    const next = redoStackRef.current.pop();
    if (!next) return;
    undoStackRef.current.push(cloneLayout(layoutRef.current));
    updateHistoryCounts();
    restoreHistoryLayout(next);
  }, [restoreHistoryLayout, updateHistoryCounts]);

  const handleSelect = useCallback(
    async (scheme: Scheme) => {
      setSelected(scheme);
      setLayout(layoutForScheme(scheme));
      try {
        const detail = await getScheme(scheme.id);
        replaceScheme(detail);
      } catch (err) {
        reportError(err, "Couldn't open scheme.");
      }
    },
    [replaceScheme, reportError],
  );

  const handleCreate = useCallback(async () => {
    const value = prompt.trim();
    if (!value || creating) return;
    setCreating(true);
    try {
      const created = await createScheme({ prompt: value });
      setPrompt("");
      setSchemes((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setSelected(created);
      setLayout(layoutForScheme(created));
    } catch (err) {
      reportError(err, "Couldn't create scheme.");
    } finally {
      setCreating(false);
    }
  }, [creating, prompt, reportError]);

  const handleRefresh = useCallback(async () => {
    if (!selected || refreshing) return;
    setRefreshing(true);
    try {
      const revision = await refreshScheme(selected.id);
      const next = applyRevision(selected, revision);
      replaceScheme(next);
    } catch (err) {
      reportError(err, "Couldn't refresh scheme.");
    } finally {
      setRefreshing(false);
    }
  }, [refreshing, replaceScheme, reportError, selected]);

  const pointFromEvent = useCallback(
    (event: PointerEvent<Element>): SchemePosition => {
      const rect = viewportRef.current?.getBoundingClientRect();
      if (!rect) return { x: 0, y: 0 };
      return {
        x:
          (event.clientX - rect.left - rect.width / 2 - layoutRef.current.viewport.x) /
          layoutRef.current.viewport.zoom,
        y:
          (event.clientY - rect.top - rect.height / 2 - layoutRef.current.viewport.y) /
          layoutRef.current.viewport.zoom,
      };
    },
    [],
  );

  const updateViewport = useCallback(
    (viewport: SchemeViewport, shouldCommit = false) => {
      const nextLayout = { ...layoutRef.current, viewport };
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      if (shouldCommit) void commitLayout(nextLayout);
    },
    [commitLayout],
  );

  const addCard = useCallback(
    (point: SchemePosition) => {
      pushUndoSnapshot();
      const card: SchemeCanvasCard = {
        id: createId("card"),
        x: point.x - STICKY_WIDTH / 2,
        y: point.y - STICKY_HEIGHT / 2,
        width: STICKY_WIDTH,
        height: STICKY_HEIGHT,
        text: locale === "ru" ? "Заметка" : "Note",
        color: "#f7d774",
        locked: false,
        z_index: nextLayerIndex(layoutRef.current),
      };
      const nextLayout = { ...layoutRef.current, cards: [...layoutRef.current.cards, card] };
      setSelectedItem(card.id);
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout, locale, pushUndoSnapshot],
  );

  const addShape = useCallback(
    (point: SchemePosition, kind: SchemeShapeKind) => {
      pushUndoSnapshot();
      const shape: SchemeCanvasShape = {
        id: createId("shape"),
        kind,
        x: point.x - SHAPE_WIDTH / 2,
        y: point.y - SHAPE_HEIGHT / 2,
        width: SHAPE_WIDTH,
        height: SHAPE_HEIGHT,
        color: kind === "ellipse" ? "#7c3aed" : "#2563eb",
        fill: "transparent",
        locked: false,
        z_index: nextLayerIndex(layoutRef.current),
      };
      const nextLayout = { ...layoutRef.current, shapes: [...layoutRef.current.shapes, shape] };
      setSelectedItem(shape.id);
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout, pushUndoSnapshot],
  );

  const addFrame = useCallback(
    (point: SchemePosition) => {
      pushUndoSnapshot();
      const frame: SchemeCanvasFrame = {
        id: createId("frame"),
        x: point.x - FRAME_WIDTH / 2,
        y: point.y - FRAME_HEIGHT / 2,
        width: FRAME_WIDTH,
        height: FRAME_HEIGHT,
        title: locale === "ru" ? "Фрейм" : "Frame",
        color: "#0f766e",
        fill: "transparent",
        locked: false,
        z_index: nextLayerIndex(layoutRef.current),
      };
      const nextLayout = { ...layoutRef.current, frames: [...layoutRef.current.frames, frame] };
      setSelectedItem(frame.id);
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout, locale, pushUndoSnapshot],
  );

  const addText = useCallback(
    (point: SchemePosition) => {
      pushUndoSnapshot();
      const text: SchemeTextBlock = {
        id: createId("text"),
        x: point.x - TEXT_WIDTH / 2,
        y: point.y - TEXT_HEIGHT / 2,
        width: TEXT_WIDTH,
        height: TEXT_HEIGHT,
        text: locale === "ru" ? "Текст" : "Text",
        color: "#111827",
        font_size: 22,
        locked: false,
        z_index: nextLayerIndex(layoutRef.current),
      };
      const nextLayout = { ...layoutRef.current, texts: [...layoutRef.current.texts, text] };
      setSelectedItem(text.id);
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout, locale, pushUndoSnapshot],
  );

  const addConnector = useCallback(
    (source: BoardItemHandle, target: BoardItemHandle) => {
      if (source.id === target.id) return;
      pushUndoSnapshot();
      const connector: SchemeConnector = {
        id: createId("connector"),
        source_id: source.id,
        target_id: target.id,
        points: [],
        label: null,
        color: "#475569",
        locked: false,
        z_index: nextLayerIndex(layoutRef.current),
      };
      const nextLayout = {
        ...layoutRef.current,
        connectors: [...layoutRef.current.connectors, connector],
      };
      setPendingConnector(null);
      setSelectedItem(connector.id);
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout, pushUndoSnapshot],
  );

  const handleItemPointerDown = useCallback(
    (event: PointerEvent<Element>, item: BoardItemHandle, position: SchemePosition) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      setSelectedItem(item.id);
      if (isLayoutItemLocked(item.id, layoutRef.current)) {
        return;
      }
      if (tool === "connector") {
        if (pendingConnector) {
          addConnector(pendingConnector, item);
        } else {
          setPendingConnector(item);
        }
        return;
      }
      if (tool !== "select") return;
      event.currentTarget.setPointerCapture?.(event.pointerId);
      const start = pointFromEvent(event);
      pushUndoSnapshot();
      if (item.kind === "node") {
        dragRef.current = { type: "node", nodeId: item.id, start, origin: position };
      } else if (item.kind === "card") {
        dragRef.current = { type: "card", cardId: item.id, start, origin: position };
      } else if (item.kind === "shape") {
        dragRef.current = { type: "shape", shapeId: item.id, start, origin: position };
      } else if (item.kind === "frame") {
        dragRef.current = { type: "frame", frameId: item.id, start, origin: position };
      } else {
        dragRef.current = { type: "text", textId: item.id, start, origin: position };
      }
    },
    [addConnector, pendingConnector, pointFromEvent, pushUndoSnapshot, tool],
  );

  const handleViewportPointerDown = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0 || !selected) return;
      const target = event.target as HTMLElement;
      if (target.closest("[data-scheme-board-item='true']")) return;
      event.currentTarget.setPointerCapture?.(event.pointerId);
      const point = pointFromEvent(event);
      setSelectedItem(null);
      setPendingConnector(null);

      if (tool === "draw") {
        pushUndoSnapshot();
        const stroke: SchemeStroke = {
          id: createId("stroke"),
          points: [point, point],
          color: "#111827",
          width: 3,
          locked: false,
          z_index: nextLayerIndex(layoutRef.current),
        };
        const nextLayout = { ...layoutRef.current, strokes: [...layoutRef.current.strokes, stroke] };
        setLayout(nextLayout);
        layoutRef.current = nextLayout;
        dragRef.current = { type: "stroke", strokeId: stroke.id };
        return;
      }
      if (tool === "sticky") {
        addCard(point);
        return;
      }
      if (tool === "text") {
        addText(point);
        return;
      }
      if (tool === "rectangle" || tool === "ellipse") {
        addShape(point, tool);
        return;
      }
      if (tool === "frame") {
        addFrame(point);
        return;
      }
      if (tool === "pan" || tool === "select") {
        dragRef.current = {
          type: "pan",
          startClientX: event.clientX,
          startClientY: event.clientY,
          origin: layoutRef.current.viewport,
        };
      }
    },
    [addCard, addFrame, addShape, addText, pointFromEvent, pushUndoSnapshot, selected, tool],
  );

  const handlePointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag) return;
      if (drag.type === "pan") {
        const nextViewport = {
          ...drag.origin,
          x: drag.origin.x + event.clientX - drag.startClientX,
          y: drag.origin.y + event.clientY - drag.startClientY,
        };
        updateViewport(nextViewport);
        return;
      }
      if (drag.type === "stroke") {
        const point = pointFromEvent(event);
        setLocalLayout((current) => ({
          ...current,
          strokes: current.strokes.map((stroke) =>
            stroke.id === drag.strokeId
              ? { ...stroke, points: [...stroke.points, point] }
              : stroke,
          ),
        }));
        return;
      }

      const point = pointFromEvent(event);
      const dx = point.x - drag.start.x;
      const dy = point.y - drag.start.y;
      if (drag.type === "node") {
        setLocalLayout((current) => ({
          ...current,
          node_positions: {
            ...current.node_positions,
            [drag.nodeId]: { x: drag.origin.x + dx, y: drag.origin.y + dy },
          },
        }));
      } else if (drag.type === "card") {
        setLocalLayout((current) => ({
          ...current,
          cards: current.cards.map((card) =>
            card.id === drag.cardId ? { ...card, x: drag.origin.x + dx, y: drag.origin.y + dy } : card,
          ),
        }));
      } else if (drag.type === "shape") {
        setLocalLayout((current) => ({
          ...current,
          shapes: current.shapes.map((shape) =>
            shape.id === drag.shapeId
              ? { ...shape, x: drag.origin.x + dx, y: drag.origin.y + dy }
              : shape,
          ),
        }));
      } else if (drag.type === "frame") {
        setLocalLayout((current) => ({
          ...current,
          frames: current.frames.map((frame) =>
            frame.id === drag.frameId
              ? { ...frame, x: drag.origin.x + dx, y: drag.origin.y + dy }
              : frame,
          ),
        }));
      } else if (drag.type === "text") {
        setLocalLayout((current) => ({
          ...current,
          texts: current.texts.map((text) =>
            text.id === drag.textId
              ? { ...text, x: drag.origin.x + dx, y: drag.origin.y + dy }
              : text,
          ),
        }));
      }
    },
    [pointFromEvent, setLocalLayout, updateViewport],
  );

  const handlePointerUp = useCallback(() => {
    if (!dragRef.current) return;
    const drag = dragRef.current;
    dragRef.current = null;
    if (
      drag.type === "pan" ||
      drag.type === "stroke" ||
      drag.type === "node" ||
      drag.type === "card" ||
      drag.type === "shape" ||
      drag.type === "frame" ||
      drag.type === "text"
    ) {
      void commitLayout(layoutRef.current);
    }
  }, [commitLayout]);

  const handleWheel = useCallback(
    (event: WheelEvent<HTMLDivElement>) => {
      if (!selected) return;
      event.preventDefault();
      const rect = viewportRef.current?.getBoundingClientRect();
      if (!rect) return;
      const current = layoutRef.current.viewport;
      const before = {
        x: (event.clientX - rect.left - rect.width / 2 - current.x) / current.zoom,
        y: (event.clientY - rect.top - rect.height / 2 - current.y) / current.zoom,
      };
      const nextZoom = clamp(current.zoom * (event.deltaY > 0 ? 0.92 : 1.08), MIN_ZOOM, MAX_ZOOM);
      const nextViewport = {
        x: event.clientX - rect.left - rect.width / 2 - before.x * nextZoom,
        y: event.clientY - rect.top - rect.height / 2 - before.y * nextZoom,
        zoom: nextZoom,
      };
      updateViewport(nextViewport);
      if (wheelCommitRef.current !== null) {
        window.clearTimeout(wheelCommitRef.current);
      }
      wheelCommitRef.current = window.setTimeout(() => {
        void commitLayout(layoutRef.current);
        wheelCommitRef.current = null;
      }, 300);
    },
    [commitLayout, selected, updateViewport],
  );

  const handleCardTextChange = useCallback((cardId: string, text: string) => {
    setLocalLayout((current) => ({
      ...current,
      cards: current.cards.map((card) => (card.id === cardId && !card.locked ? { ...card, text } : card)),
    }));
  }, [setLocalLayout]);

  const beginInlineEdit = useCallback(
    (itemId: string) => {
      if (isLayoutItemLocked(itemId, layoutRef.current)) return;
      if (editingItemRef.current === itemId) return;
      pushUndoSnapshot();
      editingItemRef.current = itemId;
    },
    [pushUndoSnapshot],
  );

  const finishInlineEdit = useCallback(() => {
    editingItemRef.current = null;
    void commitLayout(layoutRef.current);
  }, [commitLayout]);

  const handleFrameTitleChange = useCallback((frameId: string, title: string) => {
    setLocalLayout((current) => ({
      ...current,
      frames: current.frames.map((frame) => (frame.id === frameId && !frame.locked ? { ...frame, title } : frame)),
    }));
  }, [setLocalLayout]);

  const handleTextBlockChange = useCallback((textId: string, text: string) => {
    setLocalLayout((current) => ({
      ...current,
      texts: current.texts.map((block) => (block.id === textId && !block.locked ? { ...block, text } : block)),
    }));
  }, [setLocalLayout]);

  const deleteSelected = useCallback(() => {
    if (!selectedItem || !canDeleteSelected) return;
    pushUndoSnapshot();
    const nextLayout = {
      ...layoutRef.current,
      cards: layoutRef.current.cards.filter((card) => card.id !== selectedItem),
      shapes: layoutRef.current.shapes.filter((shape) => shape.id !== selectedItem),
      frames: layoutRef.current.frames.filter((frame) => frame.id !== selectedItem),
      texts: layoutRef.current.texts.filter((text) => text.id !== selectedItem),
      strokes: layoutRef.current.strokes.filter((stroke) => stroke.id !== selectedItem),
      connectors: layoutRef.current.connectors.filter(
        (connector) =>
          connector.id !== selectedItem &&
          connector.source_id !== selectedItem &&
          connector.target_id !== selectedItem,
      ),
    };
    setSelectedItem(null);
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [canDeleteSelected, commitLayout, pushUndoSnapshot, selectedItem]);

  const toggleSelectedLock = useCallback(() => {
    if (!selectedItem || !canLockSelected) return;
    pushUndoSnapshot();
    const nextLocked = !isLayoutItemLocked(selectedItem, layoutRef.current);
    const nextLayout = {
      ...layoutRef.current,
      cards: layoutRef.current.cards.map((card) =>
        card.id === selectedItem ? { ...card, locked: nextLocked } : card,
      ),
      shapes: layoutRef.current.shapes.map((shape) =>
        shape.id === selectedItem ? { ...shape, locked: nextLocked } : shape,
      ),
      frames: layoutRef.current.frames.map((frame) =>
        frame.id === selectedItem ? { ...frame, locked: nextLocked } : frame,
      ),
      texts: layoutRef.current.texts.map((text) =>
        text.id === selectedItem ? { ...text, locked: nextLocked } : text,
      ),
      strokes: layoutRef.current.strokes.map((stroke) =>
        stroke.id === selectedItem ? { ...stroke, locked: nextLocked } : stroke,
      ),
      connectors: layoutRef.current.connectors.map((connector) =>
        connector.id === selectedItem ? { ...connector, locked: nextLocked } : connector,
      ),
    };
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [canLockSelected, commitLayout, pushUndoSnapshot, selectedItem]);

  const arrangeSelected = useCallback((action: LayerAction) => {
    if (!selectedItem || !canArrangeSelected) return;
    pushUndoSnapshot();
    const nextLayout = arrangeLayoutItem(layoutRef.current, selectedItem, action);
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [canArrangeSelected, commitLayout, pushUndoSnapshot, selectedItem]);

  const duplicateSelected = useCallback(() => {
    if (!selectedItem || !canDuplicateSelected) return;
    pushUndoSnapshot();
    const offset = 32;
    let nextSelectedItem: string | null = null;
    const current = layoutRef.current;
    const nextLayout = cloneLayout(current);

    const card = current.cards.find((candidate) => candidate.id === selectedItem);
    if (card) {
      const duplicate = { ...card, id: createId("card"), x: card.x + offset, y: card.y + offset, z_index: nextLayerIndex(current) };
      nextLayout.cards.push(duplicate);
      nextSelectedItem = duplicate.id;
    }

    const shape = current.shapes.find((candidate) => candidate.id === selectedItem);
    if (shape) {
      const duplicate = { ...shape, id: createId("shape"), x: shape.x + offset, y: shape.y + offset, z_index: nextLayerIndex(current) };
      nextLayout.shapes.push(duplicate);
      nextSelectedItem = duplicate.id;
    }

    const frame = current.frames.find((candidate) => candidate.id === selectedItem);
    if (frame) {
      const duplicate = { ...frame, id: createId("frame"), x: frame.x + offset, y: frame.y + offset, z_index: nextLayerIndex(current) };
      nextLayout.frames.push(duplicate);
      nextSelectedItem = duplicate.id;
    }

    const text = current.texts.find((candidate) => candidate.id === selectedItem);
    if (text) {
      const duplicate = { ...text, id: createId("text"), x: text.x + offset, y: text.y + offset, z_index: nextLayerIndex(current) };
      nextLayout.texts.push(duplicate);
      nextSelectedItem = duplicate.id;
    }

    const stroke = current.strokes.find((candidate) => candidate.id === selectedItem);
    if (stroke) {
      const duplicate = {
        ...stroke,
        id: createId("stroke"),
        points: stroke.points.map((point) => ({ x: point.x + offset, y: point.y + offset })),
        z_index: nextLayerIndex(current),
      };
      nextLayout.strokes.push(duplicate);
      nextSelectedItem = duplicate.id;
    }

    if (!nextSelectedItem) return;
    setSelectedItem(nextSelectedItem);
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [canDuplicateSelected, commitLayout, pushUndoSnapshot, selectedItem]);

  const setZoom = useCallback(
    (nextZoom: number) => {
      updateViewport({ ...layoutRef.current.viewport, zoom: clamp(nextZoom, MIN_ZOOM, MAX_ZOOM) }, true);
    },
    [updateViewport],
  );

  const resetView = useCallback(() => {
    updateViewport({ ...DEFAULT_VIEWPORT }, true);
  }, [updateViewport]);

  const worldTransform = `translate(${layout.viewport.x}px, ${layout.viewport.y}px) scale(${layout.viewport.zoom})`;

  return (
    <section className="schemes-panel" data-testid="schemes-panel">
      <header className="schemes-panel__header">
        <div>
          <h3>{copy.title}</h3>
          <p>{copy.subtitle}</p>
        </div>
        <form
          className="schemes-panel__create"
          onSubmit={(event) => {
            event.preventDefault();
            void handleCreate();
          }}
        >
          <input
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder={copy.promptPlaceholder}
            aria-label={copy.promptPlaceholder}
          />
          <button type="submit" disabled={!prompt.trim() || creating}>
            {creating ? copy.creating : copy.create}
          </button>
        </form>
      </header>

      <div className="schemes-panel__body">
        <aside className="schemes-panel__list" aria-label={copy.title}>
          {loading ? (
            <p className="schemes-panel__status">{copy.loading}</p>
          ) : schemes.length === 0 ? (
            <div className="schemes-panel__empty">
              <strong>{copy.emptyTitle}</strong>
              <span>{copy.emptyBody}</span>
            </div>
          ) : (
            schemes.map((scheme) => (
              <button
                key={scheme.id}
                type="button"
                className={`scheme-list-row ${selected?.id === scheme.id ? "scheme-list-row--active" : ""}`}
                aria-current={selected?.id === scheme.id ? "true" : undefined}
                onClick={() => void handleSelect(scheme)}
              >
                <strong>{scheme.title}</strong>
                <span>
                  {nodeKindLabel(scheme.scheme_type)} /{" "}
                  {copy.source(scheme.current_revision?.source_count ?? 0)}
                </span>
              </button>
            ))
          )}
        </aside>

        <div className="scheme-board">
          <div className="scheme-board__toolbar">
            <div>
              <strong>{selected?.title ?? copy.title}</strong>
              <span>
                {projection?.summary ?? (selected ? copy.noProjection : copy.noSelection)}
              </span>
            </div>
            <div className="scheme-board__actions">
              {selected ? <span>{copy.source(selected.current_revision?.source_count ?? 0)}</span> : null}
              <button type="button" disabled={historyCounts.undo === 0} onClick={undoLayout}>
                {copy.undo}
              </button>
              <button type="button" disabled={historyCounts.redo === 0} onClick={redoLayout}>
                {copy.redo}
              </button>
              <button type="button" onClick={() => setZoom(layout.viewport.zoom - 0.12)}>
                {copy.zoomOut}
              </button>
              <button type="button" onClick={() => setZoom(layout.viewport.zoom + 0.12)}>
                {copy.zoomIn}
              </button>
              <button type="button" onClick={resetView}>
                {copy.reset}
              </button>
              <button type="button" disabled={!canDeleteSelected} onClick={deleteSelected}>
                {copy.delete}
              </button>
              <button type="button" disabled={!canLockSelected} onClick={toggleSelectedLock}>
                {selectedItemLocked ? copy.unlock : copy.lock}
              </button>
              <button type="button" disabled={!canArrangeSelected} onClick={() => arrangeSelected("front")}>
                {copy.bringFront}
              </button>
              <button type="button" disabled={!canArrangeSelected} onClick={() => arrangeSelected("forward")}>
                {copy.bringForward}
              </button>
              <button type="button" disabled={!canArrangeSelected} onClick={() => arrangeSelected("backward")}>
                {copy.sendBackward}
              </button>
              <button type="button" disabled={!canArrangeSelected} onClick={() => arrangeSelected("back")}>
                {copy.sendBack}
              </button>
              <button type="button" disabled={!canDuplicateSelected} onClick={duplicateSelected}>
                {copy.duplicate}
              </button>
              <button type="button" disabled={!selected || refreshing} onClick={() => void handleRefresh()}>
                {refreshing ? copy.refreshing : copy.refresh}
              </button>
            </div>
          </div>

          <div className="scheme-board__tools" role="toolbar" aria-label="Scheme board tools">
            {TOOLS.map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                className={tool === candidate.id ? "scheme-board__tool scheme-board__tool--active" : "scheme-board__tool"}
                aria-pressed={tool === candidate.id}
                onClick={() => {
                  setTool(candidate.id);
                  setPendingConnector(null);
                }}
              >
                {locale === "ru" ? candidate.ru : candidate.label}
              </button>
            ))}
            {pendingConnector ? <span>{copy.connectorHint}</span> : null}
          </div>

          {selected ? (
            <div
              ref={viewportRef}
              className={`scheme-board__viewport scheme-board__viewport--${tool}`}
              onPointerDown={handleViewportPointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerUp}
              onWheel={handleWheel}
            >
              <div className="scheme-board__grid" />
              <div className="scheme-board__world" style={{ transform: worldTransform }}>
                <svg className="scheme-board__edges" aria-hidden="true">
                  {projection?.edges.map((edge) => {
                    const source = nodeById.get(edge.source);
                    const target = nodeById.get(edge.target);
                    if (!source || !target) return null;
                    return (
                      <line
                        key={edge.id}
                        x1={source.position.x + NODE_WIDTH / 2}
                        y1={source.position.y + NODE_HEIGHT / 2}
                        x2={target.position.x + NODE_WIDTH / 2}
                        y2={target.position.y + NODE_HEIGHT / 2}
                      />
                    );
                  })}
                </svg>

                {layout.connectors.map((connector) => {
                  const source = itemCenter(connector.source_id, positionedNodes, layout);
                  const target = itemCenter(connector.target_id, positionedNodes, layout);
                  const points = source && target ? [source, target] : connector.points;
                  if (points.length < 2) return null;
                  return (
                    <svg
                      key={connector.id}
                      data-scheme-board-item="true"
                      className="scheme-board__svg-item"
                      aria-hidden="true"
                      style={{ zIndex: layerZIndex(connector.z_index) }}
                    >
                      <polyline
                        className={[
                          selectedItem === connector.id ? "scheme-board__connector--selected" : "",
                          connector.locked ? "scheme-board__item--locked" : "",
                        ].filter(Boolean).join(" ")}
                        points={points.map((point) => `${point.x},${point.y}`).join(" ")}
                        stroke={connector.color}
                        onPointerDown={(event) => {
                          event.stopPropagation();
                          setSelectedItem(connector.id);
                        }}
                      />
                    </svg>
                  );
                })}

                {layout.strokes.map((stroke) => (
                  <svg
                    key={stroke.id}
                    data-scheme-board-item="true"
                    className="scheme-board__svg-item"
                    aria-hidden="true"
                    style={{ zIndex: layerZIndex(stroke.z_index) }}
                  >
                    <polyline
                      className={[
                        selectedItem === stroke.id ? "scheme-board__stroke--selected" : "",
                        stroke.locked ? "scheme-board__item--locked" : "",
                      ].filter(Boolean).join(" ")}
                      points={stroke.points.map((point) => `${point.x},${point.y}`).join(" ")}
                      stroke={stroke.color}
                      strokeWidth={stroke.width}
                      onPointerDown={(event) => {
                        event.stopPropagation();
                        setSelectedItem(stroke.id);
                      }}
                    />
                  </svg>
                ))}

                {layout.shapes.map((shape) => (
                  <svg
                    key={shape.id}
                    data-scheme-board-item="true"
                    className="scheme-board__svg-item"
                    aria-hidden="true"
                    style={{ zIndex: layerZIndex(shape.z_index) }}
                  >
                    <path
                      className={[
                        selectedItem === shape.id ? "scheme-board__shape--selected" : "",
                        shape.locked ? "scheme-board__item--locked" : "",
                      ].filter(Boolean).join(" ")}
                      d={shapePath(shape)}
                      stroke={shape.color}
                      fill={shape.fill}
                      onPointerDown={(event) =>
                        handleItemPointerDown(event, { id: shape.id, kind: "shape" }, { x: shape.x, y: shape.y })
                      }
                    />
                  </svg>
                ))}

                {layout.frames.map((frame) => (
                  <div
                    key={frame.id}
                    data-scheme-board-item="true"
                    className={[
                      "scheme-frame",
                      selectedItem === frame.id ? "scheme-frame--selected" : "",
                      frame.locked ? "scheme-board__item--locked" : "",
                    ].filter(Boolean).join(" ")}
                    style={{
                      left: frame.x,
                      top: frame.y,
                      width: frame.width,
                      height: frame.height,
                      borderColor: frame.color,
                      backgroundColor: frame.fill === "transparent" ? undefined : frame.fill,
                      zIndex: layerZIndex(frame.z_index),
                    }}
                    onPointerDown={(event) =>
                      handleItemPointerDown(event, { id: frame.id, kind: "frame" }, { x: frame.x, y: frame.y })
                    }
                  >
                    <input
                      value={frame.title}
                      aria-label="Frame title"
                      disabled={frame.locked}
                      onPointerDown={(event) => {
                        event.stopPropagation();
                        setSelectedItem(frame.id);
                      }}
                      onFocus={() => beginInlineEdit(frame.id)}
                      onChange={(event) => handleFrameTitleChange(frame.id, event.target.value)}
                      onBlur={finishInlineEdit}
                    />
                  </div>
                ))}

                {layout.texts.map((text) => (
                  <div
                    key={text.id}
                    data-scheme-board-item="true"
                    className={[
                      "scheme-text",
                      selectedItem === text.id ? "scheme-text--selected" : "",
                      text.locked ? "scheme-board__item--locked" : "",
                    ].filter(Boolean).join(" ")}
                    style={{
                      left: text.x,
                      top: text.y,
                      width: text.width,
                      height: text.height,
                      color: text.color,
                      fontSize: text.font_size,
                      zIndex: layerZIndex(text.z_index),
                    }}
                    onPointerDown={(event) =>
                      handleItemPointerDown(event, { id: text.id, kind: "text" }, { x: text.x, y: text.y })
                    }
                  >
                    <textarea
                      value={text.text}
                      aria-label="Canvas text"
                      disabled={text.locked}
                      onPointerDown={(event) => {
                        event.stopPropagation();
                        setSelectedItem(text.id);
                      }}
                      onFocus={() => beginInlineEdit(text.id)}
                      onChange={(event) => handleTextBlockChange(text.id, event.target.value)}
                      onBlur={finishInlineEdit}
                    />
                  </div>
                ))}

                {positionedNodes.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    data-scheme-board-item="true"
                    className={`scheme-node scheme-node--${node.kind} ${selectedItem === node.id ? "scheme-node--selected" : ""}`}
                    style={{ left: node.position.x, top: node.position.y, zIndex: 20 }}
                    aria-label={`${node.title} ${node.body ?? ""}`.trim()}
                    onPointerDown={(event) =>
                      handleItemPointerDown(event, { id: node.id, kind: "node" }, node.position)
                    }
                  >
                    <span>{nodeKindLabel(node.kind)}</span>
                    <strong>{node.title}</strong>
                    {node.body ? <small>{node.body}</small> : null}
                  </button>
                ))}

                {layout.cards.map((card) => (
                  <div
                    key={card.id}
                    data-scheme-board-item="true"
                    className={[
                      "scheme-sticky",
                      selectedItem === card.id ? "scheme-sticky--selected" : "",
                      card.locked ? "scheme-board__item--locked" : "",
                    ].filter(Boolean).join(" ")}
                    style={{
                      left: card.x,
                      top: card.y,
                      width: card.width,
                      height: card.height,
                      backgroundColor: card.color,
                      zIndex: layerZIndex(card.z_index),
                    }}
                    onPointerDown={(event) =>
                      handleItemPointerDown(event, { id: card.id, kind: "card" }, { x: card.x, y: card.y })
                    }
                  >
                    <textarea
                      value={card.text}
                      aria-label="Sticky note"
                      disabled={card.locked}
                      onPointerDown={(event) => {
                        event.stopPropagation();
                        setSelectedItem(card.id);
                      }}
                      onFocus={() => beginInlineEdit(card.id)}
                      onChange={(event) => handleCardTextChange(card.id, event.target.value)}
                      onBlur={finishInlineEdit}
                    />
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="scheme-board__placeholder">{copy.noSelection}</div>
          )}
        </div>
      </div>
    </section>
  );
}
