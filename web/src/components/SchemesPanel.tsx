"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, MouseEvent, PointerEvent, WheelEvent } from "react";
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
  SchemeCanvasSourceBlock,
  SchemeConnector,
  SchemeNode,
  SchemePosition,
  SchemeProjection,
  SchemeShapeKind,
  SchemeStroke,
  SchemeStrokeKind,
  SchemeStrokePoint,
  SchemeTextBlock,
  SchemeViewport,
} from "@/lib/types";

type Locale = "en" | "ru";
type Tool =
  | "select"
  | "pan"
  | "lasso"
  | "draw"
  | "highlighter"
  | "eraser"
  | "sticky"
  | "text"
  | "rectangle"
  | "ellipse"
  | "frame"
  | "connector";
type BoardItemKind = "node" | "card" | "shape" | "frame" | "text" | "source";
type ResizableItemKind = Exclude<BoardItemKind, "node">;
type ResizeHandle = "nw" | "ne" | "sw" | "se";
interface SchemesPanelProps {
  locale?: Locale;
  onError?: (message: string) => void;
}

interface BoardItemBounds {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface ResizeLimits {
  minWidth: number;
  minHeight: number;
  maxWidth: number;
  maxHeight: number;
}

interface SelectionRect {
  x: number;
  y: number;
  width: number;
  height: number;
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
      type: "source";
      sourceId: string;
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
    }
  | {
      type: "eraser";
    }
  | {
      type: "multi";
      start: SchemePosition;
      origin: SchemeCanvasLayout;
      itemIds: string[];
    }
  | {
      type: "resize";
      itemId: string;
      itemKind: ResizableItemKind;
      handle: ResizeHandle;
      start: SchemePosition;
      origin: BoardItemBounds;
    }
  | {
      type: "marquee";
      start: SchemePosition;
      current: SchemePosition;
      previousItemIds: string[];
    }
  | {
      type: "lasso";
      points: SchemePosition[];
      previousItemIds: string[];
    };

interface BoardItemHandle {
  id: string;
  kind: BoardItemKind;
}

interface ProjectionSourceSummary {
  id: string;
  source_kind: "item" | "recording" | "chat";
  source_id: string;
  title: string;
  kind?: string | null;
  created_at?: string | null;
}

const SCHEME_LAYOUT_VERSION = 7 as const;
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
const SOURCE_WIDTH = 320;
const SOURCE_HEIGHT = 170;
const RESIZE_LIMITS: Record<ResizableItemKind, ResizeLimits> = {
  card: { minWidth: 24, minHeight: 24, maxWidth: 1200, maxHeight: 1200 },
  shape: { minWidth: 16, minHeight: 16, maxWidth: 2000, maxHeight: 2000 },
  frame: { minWidth: 88, minHeight: 88, maxWidth: 4000, maxHeight: 4000 },
  text: { minWidth: 24, minHeight: 24, maxWidth: 1600, maxHeight: 1600 },
  source: { minWidth: 88, minHeight: 68, maxWidth: 1600, maxHeight: 1600 },
};
const RESIZE_HANDLES: ResizeHandle[] = ["nw", "ne", "sw", "se"];
const MAX_PINNED_SOURCE_BLOCKS = 12;
const DEFAULT_PEN_COLOR = "#111827";
const DEFAULT_HIGHLIGHTER_COLOR = "#facc15";
const DEFAULT_PEN_WIDTH = 3;
const DEFAULT_HIGHLIGHTER_WIDTH = 14;
const DEFAULT_HIGHLIGHTER_OPACITY = 0.35;
const ERASER_RADIUS = 14;
const PEN_COLORS = ["#111827", "#dc2626", "#2563eb", "#16a34a", "#7c3aed"];
const PEN_WIDTHS = [2, 3, 5, 8];
const TOOLS: Array<{ id: Tool; label: string; ru: string }> = [
  { id: "select", label: "Select", ru: "Выбор" },
  { id: "pan", label: "Hand", ru: "Рука" },
  { id: "lasso", label: "Lasso", ru: "Лассо" },
  { id: "draw", label: "Pen", ru: "Перо" },
  { id: "highlighter", label: "Highlight", ru: "Маркер" },
  { id: "eraser", label: "Erase", ru: "Ластик" },
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
    pinSources: "Pin sources",
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
    pinSources: "Закрепить источники",
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
    sources: [],
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
    sources: withIndex(layout.sources),
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

function normaliseStrokePoint(point: SchemePosition | SchemeStrokePoint): SchemeStrokePoint {
  const pressure = (point as SchemeStrokePoint).pressure;
  return {
    x: point.x,
    y: point.y,
    pressure: typeof pressure === "number" && Number.isFinite(pressure) ? clamp(pressure, 0, 1) : 1,
  };
}

function normaliseStroke(stroke: SchemeStroke): SchemeStroke {
  const kind: SchemeStrokeKind = stroke.kind === "highlighter" ? "highlighter" : "pen";
  return {
    ...stroke,
    kind,
    color: stroke.color ?? (kind === "highlighter" ? DEFAULT_HIGHLIGHTER_COLOR : DEFAULT_PEN_COLOR),
    width: stroke.width ?? (kind === "highlighter" ? DEFAULT_HIGHLIGHTER_WIDTH : DEFAULT_PEN_WIDTH),
    opacity: stroke.opacity ?? (kind === "highlighter" ? DEFAULT_HIGHLIGHTER_OPACITY : 1),
    points: (stroke.points ?? []).map(normaliseStrokePoint),
    locked: stroke.locked ?? false,
    z_index: stroke.z_index ?? Number.NaN,
  };
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
    strokes: (raw.strokes ?? []).map(normaliseStroke),
    cards: (raw.cards ?? []).map((card) => ({ ...card, locked: card.locked ?? false, z_index: card.z_index ?? Number.NaN })),
    shapes: (raw.shapes ?? []).map((shape) => ({ ...shape, locked: shape.locked ?? false, z_index: shape.z_index ?? Number.NaN })),
    frames: (raw.frames ?? []).map((frame) => ({ ...frame, locked: frame.locked ?? false, z_index: frame.z_index ?? Number.NaN })),
    texts: (raw.texts ?? []).map((text) => ({ ...text, locked: text.locked ?? false, z_index: text.z_index ?? Number.NaN })),
    sources: (raw.sources ?? []).map((source) => ({
      ...source,
      subtitle: source.subtitle ?? null,
      excerpt: source.excerpt ?? null,
      locked: source.locked ?? false,
      z_index: source.z_index ?? Number.NaN,
    })),
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function isSourceKind(value: unknown): value is ProjectionSourceSummary["source_kind"] {
  return value === "item" || value === "recording" || value === "chat";
}

function projectionSourceSummaries(projection: SchemeProjection | null): ProjectionSourceSummary[] {
  if (!projection) return [];
  return projection.citations.slice(0, MAX_PINNED_SOURCE_BLOCKS).flatMap((candidate) => {
    if (!isRecord(candidate) || !isSourceKind(candidate.source_kind)) return [];
    const id = readString(candidate.id);
    const sourceId = readString(candidate.source_id);
    const title = readString(candidate.title);
    if (!id || !sourceId || !title) return [];
    return [
      {
        id,
        source_kind: candidate.source_kind,
        source_id: sourceId,
        title,
        kind: readString(candidate.kind),
        created_at: readString(candidate.created_at),
      },
    ];
  });
}

function sourceBlockId(source: ProjectionSourceSummary): string {
  return `source-block:${source.source_kind}:${source.source_id}`;
}

function sourceKindColor(sourceKind: ProjectionSourceSummary["source_kind"]): string {
  if (sourceKind === "recording") return "#ecfeff";
  if (sourceKind === "chat") return "#f5f3ff";
  return "#eef2ff";
}

function sourceSubtitle(source: ProjectionSourceSummary): string | null {
  const parts = [source.kind, source.created_at?.slice(0, 10)].filter(Boolean);
  return parts.length > 0 ? parts.join(" / ") : source.source_kind;
}

function sourceExcerpt(source: ProjectionSourceSummary, projection: SchemeProjection): string | null {
  const node = projection.nodes.find(
    (candidate) =>
      candidate.kind === "source" &&
      candidate.source_kind === source.source_kind &&
      candidate.source_id === source.source_id,
  );
  return readString(node?.body);
}

function sourceBlockFromSummary(
  source: ProjectionSourceSummary,
  projection: SchemeProjection,
  index: number,
  zIndex: number,
): SchemeCanvasSourceBlock {
  return {
    id: sourceBlockId(source),
    source_kind: source.source_kind,
    source_id: source.source_id,
    citation_id: source.id,
    x: -760,
    y: -240 + index * (SOURCE_HEIGHT + 28),
    width: SOURCE_WIDTH,
    height: SOURCE_HEIGHT,
    title: source.title,
    subtitle: sourceSubtitle(source),
    excerpt: sourceExcerpt(source, projection),
    color: sourceKindColor(source.source_kind),
    locked: false,
    z_index: zIndex,
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
  const source = layout.sources.find((candidate) => candidate.id === itemId);
  if (source) {
    return { x: source.x + source.width / 2, y: source.y + source.height / 2 };
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
    layout.sources.some((candidate) => candidate.id === itemId && candidate.locked) ||
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
    layout.sources.some((candidate) => candidate.id === itemId) ||
    layout.strokes.some((candidate) => candidate.id === itemId) ||
    layout.connectors.some((candidate) => candidate.id === itemId)
  );
}

function canDuplicateLayoutItem(itemId: string | null, layout: SchemeCanvasLayout): boolean {
  if (!itemId || isLayoutItemLocked(itemId, layout)) return false;
  return (
    layout.cards.some((candidate) => candidate.id === itemId) ||
    layout.shapes.some((candidate) => candidate.id === itemId) ||
    layout.frames.some((candidate) => candidate.id === itemId) ||
    layout.texts.some((candidate) => candidate.id === itemId) ||
    layout.sources.some((candidate) => candidate.id === itemId) ||
    layout.strokes.some((candidate) => candidate.id === itemId)
  );
}

function isEditableElement(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
}

function normaliseRect(start: SchemePosition, end: SchemePosition): SelectionRect {
  const x = Math.min(start.x, end.x);
  const y = Math.min(start.y, end.y);
  return {
    x,
    y,
    width: Math.max(start.x, end.x) - x,
    height: Math.max(start.y, end.y) - y,
  };
}

function boundsFromPoints(id: string, points: SchemePosition[]): BoardItemBounds | null {
  if (points.length === 0) return null;
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return {
    id,
    x,
    y,
    width: Math.max(...xs) - x,
    height: Math.max(...ys) - y,
  };
}

function layoutItemBounds(layout: SchemeCanvasLayout, nodes: SchemeNode[]): BoardItemBounds[] {
  return [
    ...nodes.map((node) => ({
      id: node.id,
      x: node.position.x,
      y: node.position.y,
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    })),
    ...layout.cards.map((card) => ({
      id: card.id,
      x: card.x,
      y: card.y,
      width: card.width,
      height: card.height,
    })),
    ...layout.shapes.map((shape) => ({
      id: shape.id,
      x: shape.x,
      y: shape.y,
      width: shape.width,
      height: shape.height,
    })),
    ...layout.frames.map((frame) => ({
      id: frame.id,
      x: frame.x,
      y: frame.y,
      width: frame.width,
      height: frame.height,
    })),
    ...layout.texts.map((text) => ({
      id: text.id,
      x: text.x,
      y: text.y,
      width: text.width,
      height: text.height,
    })),
    ...layout.sources.map((source) => ({
      id: source.id,
      x: source.x,
      y: source.y,
      width: source.width,
      height: source.height,
    })),
    ...layout.strokes.flatMap((stroke) => {
      const bounds = boundsFromPoints(stroke.id, stroke.points);
      return bounds ? [bounds] : [];
    }),
    ...layout.connectors.flatMap((connector) => {
      const source = itemCenter(connector.source_id, nodes, layout);
      const target = itemCenter(connector.target_id, nodes, layout);
      const points = source && target ? [source, target] : connector.points;
      const bounds = boundsFromPoints(connector.id, points);
      return bounds ? [bounds] : [];
    }),
  ];
}

function resizableItem(
  layout: SchemeCanvasLayout,
  itemId: string,
): { kind: ResizableItemKind; bounds: BoardItemBounds; zIndex: number } | null {
  const card = layout.cards.find((candidate) => candidate.id === itemId);
  if (card) {
    return {
      kind: "card",
      bounds: { id: card.id, x: card.x, y: card.y, width: card.width, height: card.height },
      zIndex: card.z_index,
    };
  }
  const shape = layout.shapes.find((candidate) => candidate.id === itemId);
  if (shape) {
    return {
      kind: "shape",
      bounds: { id: shape.id, x: shape.x, y: shape.y, width: shape.width, height: shape.height },
      zIndex: shape.z_index,
    };
  }
  const frame = layout.frames.find((candidate) => candidate.id === itemId);
  if (frame) {
    return {
      kind: "frame",
      bounds: { id: frame.id, x: frame.x, y: frame.y, width: frame.width, height: frame.height },
      zIndex: frame.z_index,
    };
  }
  const text = layout.texts.find((candidate) => candidate.id === itemId);
  if (text) {
    return {
      kind: "text",
      bounds: { id: text.id, x: text.x, y: text.y, width: text.width, height: text.height },
      zIndex: text.z_index,
    };
  }
  const source = layout.sources.find((candidate) => candidate.id === itemId);
  if (source) {
    return {
      kind: "source",
      bounds: { id: source.id, x: source.x, y: source.y, width: source.width, height: source.height },
      zIndex: source.z_index,
    };
  }
  return null;
}

function resizedBounds(
  origin: BoardItemBounds,
  kind: ResizableItemKind,
  handle: ResizeHandle,
  dx: number,
  dy: number,
): BoardItemBounds {
  const limits = RESIZE_LIMITS[kind];
  const nextWidth = clamp(
    handle.endsWith("w") ? origin.width - dx : origin.width + dx,
    limits.minWidth,
    limits.maxWidth,
  );
  const nextHeight = clamp(
    handle.startsWith("n") ? origin.height - dy : origin.height + dy,
    limits.minHeight,
    limits.maxHeight,
  );

  return {
    id: origin.id,
    x: handle.endsWith("w") ? origin.x + origin.width - nextWidth : origin.x,
    y: handle.startsWith("n") ? origin.y + origin.height - nextHeight : origin.y,
    width: nextWidth,
    height: nextHeight,
  };
}

function resizeLayoutItem(
  layout: SchemeCanvasLayout,
  itemId: string,
  kind: ResizableItemKind,
  bounds: BoardItemBounds,
): SchemeCanvasLayout {
  if (kind === "card") {
    return {
      ...layout,
      cards: layout.cards.map((card) => (card.id === itemId ? { ...card, ...bounds } : card)),
    };
  }
  if (kind === "shape") {
    return {
      ...layout,
      shapes: layout.shapes.map((shape) => (shape.id === itemId ? { ...shape, ...bounds } : shape)),
    };
  }
  if (kind === "frame") {
    return {
      ...layout,
      frames: layout.frames.map((frame) => (frame.id === itemId ? { ...frame, ...bounds } : frame)),
    };
  }
  if (kind === "text") {
    return {
      ...layout,
      texts: layout.texts.map((text) => (text.id === itemId ? { ...text, ...bounds } : text)),
    };
  }
  return {
    ...layout,
    sources: layout.sources.map((source) => (source.id === itemId ? { ...source, ...bounds } : source)),
  };
}

function rectsIntersect(first: SelectionRect, second: BoardItemBounds): boolean {
  return (
    first.x <= second.x + second.width &&
    first.x + first.width >= second.x &&
    first.y <= second.y + second.height &&
    first.y + first.height >= second.y
  );
}

function selectedIdsFromMarquee(
  rect: SelectionRect,
  layout: SchemeCanvasLayout,
  nodes: SchemeNode[],
): string[] {
  return layoutItemBounds(layout, nodes)
    .filter((bounds) => rectsIntersect(rect, bounds))
    .map((bounds) => bounds.id);
}

function mergeSelectionIds(first: string[], second: string[]): string[] {
  return Array.from(new Set([...first, ...second]));
}

function pointInPolygon(point: SchemePosition, polygon: SchemePosition[]): boolean {
  if (polygon.length < 3) return false;
  let inside = false;
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index++) {
    const current = polygon[index];
    const prior = polygon[previous];
    const crosses =
      current.y > point.y !== prior.y > point.y &&
      point.x < ((prior.x - current.x) * (point.y - current.y)) / (prior.y - current.y) + current.x;
    if (crosses) inside = !inside;
  }
  return inside;
}

function sampledBoundsPoints(bounds: BoardItemBounds): SchemePosition[] {
  const widthSteps = bounds.width <= 1 ? 1 : 4;
  const heightSteps = bounds.height <= 1 ? 1 : 4;
  const points: SchemePosition[] = [];
  for (let xIndex = 0; xIndex <= widthSteps; xIndex += 1) {
    for (let yIndex = 0; yIndex <= heightSteps; yIndex += 1) {
      points.push({
        x: bounds.x + (bounds.width * xIndex) / widthSteps,
        y: bounds.y + (bounds.height * yIndex) / heightSteps,
      });
    }
  }
  return points;
}

function boundsMostlyInsideLasso(bounds: BoardItemBounds, polygon: SchemePosition[]): boolean {
  const samples = sampledBoundsPoints(bounds);
  const insideCount = samples.filter((point) => pointInPolygon(point, polygon)).length;
  return insideCount / samples.length >= 0.9;
}

function selectedIdsFromLasso(
  points: SchemePosition[],
  layout: SchemeCanvasLayout,
  nodes: SchemeNode[],
): string[] {
  if (points.length < 3) return [];
  return layoutItemBounds(layout, nodes)
    .filter((bounds) => boundsMostlyInsideLasso(bounds, points))
    .map((bounds) => bounds.id);
}

function translateSelectedLayout(
  layout: SchemeCanvasLayout,
  itemIds: string[],
  dx: number,
  dy: number,
): SchemeCanvasLayout {
  const selected = new Set(itemIds);
  return {
    ...layout,
    node_positions: Object.fromEntries(
      Object.entries(layout.node_positions).map(([id, position]) => [
        id,
        selected.has(id) ? { x: position.x + dx, y: position.y + dy } : position,
      ]),
    ),
    cards: layout.cards.map((card) =>
      selected.has(card.id) ? { ...card, x: card.x + dx, y: card.y + dy } : card,
    ),
    shapes: layout.shapes.map((shape) =>
      selected.has(shape.id) ? { ...shape, x: shape.x + dx, y: shape.y + dy } : shape,
    ),
    frames: layout.frames.map((frame) =>
      selected.has(frame.id) ? { ...frame, x: frame.x + dx, y: frame.y + dy } : frame,
    ),
    texts: layout.texts.map((text) =>
      selected.has(text.id) ? { ...text, x: text.x + dx, y: text.y + dy } : text,
    ),
    sources: layout.sources.map((source) =>
      selected.has(source.id) ? { ...source, x: source.x + dx, y: source.y + dy } : source,
    ),
    strokes: layout.strokes.map((stroke) =>
      selected.has(stroke.id)
        ? { ...stroke, points: stroke.points.map((point) => ({ ...point, x: point.x + dx, y: point.y + dy })) }
        : stroke,
    ),
    connectors: layout.connectors.map((connector) =>
      selected.has(connector.id)
        ? { ...connector, points: connector.points.map((point) => ({ x: point.x + dx, y: point.y + dy })) }
        : connector,
    ),
  };
}

function layoutLayerItems(layout: SchemeCanvasLayout): LayerItem[] {
  return [
    ...layout.connectors.map((connector) => ({ id: connector.id, zIndex: connector.z_index })),
    ...layout.strokes.map((stroke) => ({ id: stroke.id, zIndex: stroke.z_index })),
    ...layout.shapes.map((shape) => ({ id: shape.id, zIndex: shape.z_index })),
    ...layout.frames.map((frame) => ({ id: frame.id, zIndex: frame.z_index })),
    ...layout.texts.map((text) => ({ id: text.id, zIndex: text.z_index })),
    ...layout.sources.map((source) => ({ id: source.id, zIndex: source.z_index })),
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
    sources: layout.sources.map((source) => (source.id === itemId ? { ...source, z_index: zIndex } : source)),
    strokes: layout.strokes.map((stroke) => (stroke.id === itemId ? { ...stroke, z_index: zIndex } : stroke)),
    connectors: layout.connectors.map((connector) =>
      connector.id === itemId ? { ...connector, z_index: zIndex } : connector,
    ),
  };
}

function arrangeLayoutItems(layout: SchemeCanvasLayout, itemIds: string[], action: LayerAction): SchemeCanvasLayout {
  const normalised = normaliseLayoutLayers(layout);
  const items = layoutLayerItems(normalised).sort((a, b) => a.zIndex - b.zIndex);
  const selected = new Set(itemIds);
  if (!items.some((item) => selected.has(item.id))) return layout;

  if (action === "front") {
    let zIndex = items[items.length - 1].zIndex + 1;
    return items.reduce(
      (current, item) => (selected.has(item.id) ? setLayoutItemZIndex(current, item.id, zIndex++) : current),
      normalised,
    );
  }
  if (action === "back") {
    let zIndex = items[0].zIndex - itemIds.length;
    return items.reduce(
      (current, item) => (selected.has(item.id) ? setLayoutItemZIndex(current, item.id, zIndex++) : current),
      normalised,
    );
  }

  const ordered = [...items];
  if (action === "forward") {
    for (let index = ordered.length - 2; index >= 0; index -= 1) {
      if (selected.has(ordered[index].id) && !selected.has(ordered[index + 1].id)) {
        [ordered[index], ordered[index + 1]] = [ordered[index + 1], ordered[index]];
      }
    }
  } else {
    for (let index = 1; index < ordered.length; index += 1) {
      if (selected.has(ordered[index].id) && !selected.has(ordered[index - 1].id)) {
        [ordered[index - 1], ordered[index]] = [ordered[index], ordered[index - 1]];
      }
    }
  }

  return ordered.reduce(
    (current, item, index) => setLayoutItemZIndex(current, item.id, index + 1),
    normalised,
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

function strokePath(points: SchemeStrokePoint[]): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  if (points.length === 2) {
    return `M ${points[0].x} ${points[0].y} L ${points[1].x} ${points[1].y}`;
  }

  const commands = [`M ${points[0].x} ${points[0].y}`];
  for (let index = 1; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const mid = {
      x: (current.x + next.x) / 2,
      y: (current.y + next.y) / 2,
    };
    commands.push(`Q ${current.x} ${current.y} ${mid.x} ${mid.y}`);
  }
  const last = points[points.length - 1];
  commands.push(`L ${last.x} ${last.y}`);
  return commands.join(" ");
}

function lassoPath(points: SchemePosition[]): string {
  if (points.length === 0) return "";
  const commands = [`M ${points[0].x} ${points[0].y}`];
  for (const point of points.slice(1)) {
    commands.push(`L ${point.x} ${point.y}`);
  }
  if (points.length > 2) commands.push("Z");
  return commands.join(" ");
}

function distanceToSegment(point: SchemePosition, start: SchemePosition, end: SchemePosition): number {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  if (dx === 0 && dy === 0) {
    return Math.hypot(point.x - start.x, point.y - start.y);
  }
  const ratio = clamp(((point.x - start.x) * dx + (point.y - start.y) * dy) / (dx * dx + dy * dy), 0, 1);
  const projection = { x: start.x + ratio * dx, y: start.y + ratio * dy };
  return Math.hypot(point.x - projection.x, point.y - projection.y);
}

function strokeContainsPoint(stroke: SchemeStroke, point: SchemePosition, radius = ERASER_RADIUS): boolean {
  if (stroke.points.length < 2) return false;
  const threshold = Math.max(radius, stroke.width / 2 + 6);
  for (let index = 1; index < stroke.points.length; index += 1) {
    if (distanceToSegment(point, stroke.points[index - 1], stroke.points[index]) <= threshold) {
      return true;
    }
  }
  return false;
}

function eraseStrokesAtPoint(layout: SchemeCanvasLayout, point: SchemePosition): SchemeCanvasLayout {
  const nextStrokes = layout.strokes.filter((stroke) => stroke.locked || !strokeContainsPoint(stroke, point));
  return nextStrokes.length === layout.strokes.length ? layout : { ...layout, strokes: nextStrokes };
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
    sources: layout.sources.map((source) => ({ ...source })),
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
  const [penColor, setPenColor] = useState(DEFAULT_PEN_COLOR);
  const [penWidth, setPenWidth] = useState(DEFAULT_PEN_WIDTH);
  const [selectedItems, setSelectedItems] = useState<string[]>([]);
  const [pendingConnector, setPendingConnector] = useState<BoardItemHandle | null>(null);
  const [marquee, setMarquee] = useState<SelectionRect | null>(null);
  const [lassoPoints, setLassoPoints] = useState<SchemePosition[]>([]);
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
  const selectedItemSet = useMemo(() => new Set(selectedItems), [selectedItems]);
  selectedRef.current = selected;
  layoutRef.current = layout;

  const setSelectedItem = useCallback((itemId: string | null) => {
    setSelectedItems(itemId ? [itemId] : []);
  }, []);

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
    setMarquee(null);
    setLassoPoints([]);
    setPendingConnector(null);
    undoStackRef.current = [];
    redoStackRef.current = [];
    editingItemRef.current = null;
    setHistoryCounts({ undo: 0, redo: 0 });
  }, [selectedId, setSelectedItem]);

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
  const canDeleteSelected = useMemo(
    () =>
      selectedItems.length > 0 &&
      selectedItems.every((itemId) => canLockLayoutItem(itemId, layout) && !isLayoutItemLocked(itemId, layout)),
    [layout, selectedItems],
  );
  const canDuplicateSelected = useMemo(
    () =>
      selectedItems.length > 0 &&
      selectedItems.every((itemId) => canDuplicateLayoutItem(itemId, layout)),
    [layout, selectedItems],
  );
  const canLockSelected = useMemo(
    () => selectedItems.length > 0 && selectedItems.every((itemId) => canLockLayoutItem(itemId, layout)),
    [layout, selectedItems],
  );
  const selectedItemLocked = useMemo(
    () => canLockSelected && selectedItems.every((itemId) => isLayoutItemLocked(itemId, layout)),
    [canLockSelected, layout, selectedItems],
  );
  const canArrangeSelected = useMemo(
    () => canLockSelected && selectedItems.every((itemId) => !isLayoutItemLocked(itemId, layout)),
    [canLockSelected, layout, selectedItems],
  );
  const selectedResizable = useMemo(() => {
    if (selectedItems.length !== 1 || isLayoutItemLocked(selectedItems[0], layout)) return null;
    return resizableItem(layout, selectedItems[0]);
  }, [layout, selectedItems]);
  const projectionSources = useMemo(() => projectionSourceSummaries(projection), [projection]);
  const unpinnedProjectionSources = useMemo(() => {
    const pinned = new Set(layout.sources.map((source) => source.citation_id));
    return projectionSources.filter((source) => !pinned.has(source.id));
  }, [layout.sources, projectionSources]);

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
      setMarquee(null);
      setLassoPoints([]);
      dragRef.current = null;
      editingItemRef.current = null;
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout, setSelectedItem],
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

  const pinProjectionSources = useCallback(() => {
    if (!projection || unpinnedProjectionSources.length === 0) return;
    pushUndoSnapshot();
    let nextZIndex = nextLayerIndex(layoutRef.current);
    const sourceOffset = layoutRef.current.sources.length;
    const sourceBlocks = unpinnedProjectionSources.map((source, index) =>
      sourceBlockFromSummary(source, projection, sourceOffset + index, nextZIndex++),
    );
    const nextLayout = {
      ...layoutRef.current,
      sources: [...layoutRef.current.sources, ...sourceBlocks],
    };
    setSelectedItems(sourceBlocks.map((source) => source.id));
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [commitLayout, projection, pushUndoSnapshot, unpinnedProjectionSources]);

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

  const strokePointFromEvent = useCallback(
    (event: PointerEvent<Element>): SchemeStrokePoint => {
      const pressure = typeof event.pressure === "number" && event.pressure > 0 ? event.pressure : 1;
      return {
        ...pointFromEvent(event),
        pressure: clamp(pressure, 0, 1),
      };
    },
    [pointFromEvent],
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
    [commitLayout, locale, pushUndoSnapshot, setSelectedItem],
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
    [commitLayout, pushUndoSnapshot, setSelectedItem],
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
    [commitLayout, locale, pushUndoSnapshot, setSelectedItem],
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
    [commitLayout, locale, pushUndoSnapshot, setSelectedItem],
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
    [commitLayout, pushUndoSnapshot, setSelectedItem],
  );

  const selectBoardItem = useCallback(
    (event: MouseEvent<Element> | PointerEvent<Element>, itemId: string) => {
      event.stopPropagation();
      if (event.shiftKey || event.metaKey || event.ctrlKey) {
        setSelectedItems((current) =>
          current.includes(itemId)
            ? current.filter((candidate) => candidate !== itemId)
            : [...current, itemId],
        );
      } else {
        setSelectedItem(itemId);
      }
      setPendingConnector(null);
    },
    [setSelectedItem],
  );

  const handleItemPointerDown = useCallback(
    (event: PointerEvent<Element>, item: BoardItemHandle, position: SchemePosition) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      const additiveSelection = event.shiftKey || event.metaKey || event.ctrlKey;
      if (additiveSelection) {
        setSelectedItems((current) =>
          current.includes(item.id)
            ? current.filter((candidate) => candidate !== item.id)
            : [...current, item.id],
        );
        setPendingConnector(null);
        return;
      }

      const currentSelection = selectedItemSet.has(item.id) ? selectedItems : [item.id];
      if (!selectedItemSet.has(item.id)) {
        setSelectedItem(item.id);
      }
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
      if (currentSelection.length > 1) {
        if (currentSelection.some((itemId) => isLayoutItemLocked(itemId, layoutRef.current))) return;
        pushUndoSnapshot();
        const origin = cloneLayout(layoutRef.current);
        const nodePositions = Object.fromEntries(
          positionedNodes
            .filter((node) => currentSelection.includes(node.id))
            .map((node) => [node.id, node.position]),
        );
        origin.node_positions = { ...origin.node_positions, ...nodePositions };
        dragRef.current = { type: "multi", start, origin, itemIds: currentSelection };
        return;
      }
      pushUndoSnapshot();
      if (item.kind === "node") {
        dragRef.current = { type: "node", nodeId: item.id, start, origin: position };
      } else if (item.kind === "card") {
        dragRef.current = { type: "card", cardId: item.id, start, origin: position };
      } else if (item.kind === "shape") {
        dragRef.current = { type: "shape", shapeId: item.id, start, origin: position };
      } else if (item.kind === "frame") {
        dragRef.current = { type: "frame", frameId: item.id, start, origin: position };
      } else if (item.kind === "source") {
        dragRef.current = { type: "source", sourceId: item.id, start, origin: position };
      } else {
        dragRef.current = { type: "text", textId: item.id, start, origin: position };
      }
    },
    [
      addConnector,
      pendingConnector,
      pointFromEvent,
      positionedNodes,
      pushUndoSnapshot,
      selectedItems,
      selectedItemSet,
      setSelectedItem,
      tool,
    ],
  );

  const handleResizePointerDown = useCallback(
    (event: PointerEvent<Element>, itemId: string, itemKind: ResizableItemKind, handle: ResizeHandle) => {
      if (event.button !== 0 || isLayoutItemLocked(itemId, layoutRef.current)) return;
      event.stopPropagation();
      const item = resizableItem(layoutRef.current, itemId);
      if (!item) return;
      event.currentTarget.setPointerCapture?.(event.pointerId);
      setSelectedItem(itemId);
      setPendingConnector(null);
      pushUndoSnapshot();
      dragRef.current = {
        type: "resize",
        itemId,
        itemKind,
        handle,
        start: pointFromEvent(event),
        origin: item.bounds,
      };
    },
    [pointFromEvent, pushUndoSnapshot, setSelectedItem],
  );

  const handleViewportPointerDown = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0 || !selected) return;
      event.currentTarget.focus();
      const target = event.target as HTMLElement;
      if (target.closest("[data-scheme-board-item='true']")) return;
      event.currentTarget.setPointerCapture?.(event.pointerId);
      const point = pointFromEvent(event);
      setPendingConnector(null);

      if (tool === "draw" || tool === "highlighter") {
        const strokePoint = strokePointFromEvent(event);
        const isHighlighter = tool === "highlighter";
        setSelectedItem(null);
        pushUndoSnapshot();
        const stroke: SchemeStroke = {
          id: createId("stroke"),
          points: [strokePoint, strokePoint],
          kind: isHighlighter ? "highlighter" : "pen",
          color: isHighlighter ? DEFAULT_HIGHLIGHTER_COLOR : penColor,
          width: isHighlighter ? DEFAULT_HIGHLIGHTER_WIDTH : penWidth,
          opacity: isHighlighter ? DEFAULT_HIGHLIGHTER_OPACITY : 1,
          locked: false,
          z_index: nextLayerIndex(layoutRef.current),
        };
        const nextLayout = { ...layoutRef.current, strokes: [...layoutRef.current.strokes, stroke] };
        setLayout(nextLayout);
        layoutRef.current = nextLayout;
        dragRef.current = { type: "stroke", strokeId: stroke.id };
        return;
      }
      if (tool === "eraser") {
        setSelectedItem(null);
        pushUndoSnapshot();
        const nextLayout = eraseStrokesAtPoint(layoutRef.current, point);
        setLayout(nextLayout);
        layoutRef.current = nextLayout;
        dragRef.current = { type: "eraser" };
        return;
      }
      if (tool === "sticky") {
        setSelectedItem(null);
        addCard(point);
        return;
      }
      if (tool === "text") {
        setSelectedItem(null);
        addText(point);
        return;
      }
      if (tool === "rectangle" || tool === "ellipse") {
        setSelectedItem(null);
        addShape(point, tool);
        return;
      }
      if (tool === "frame") {
        setSelectedItem(null);
        addFrame(point);
        return;
      }
      if (tool === "select") {
        const additiveSelection = event.shiftKey || event.metaKey || event.ctrlKey;
        if (!additiveSelection) {
          setSelectedItem(null);
        }
        dragRef.current = {
          type: "marquee",
          start: point,
          current: point,
          previousItemIds: additiveSelection ? selectedItems : [],
        };
        setMarquee(normaliseRect(point, point));
        return;
      }
      if (tool === "lasso") {
        const additiveSelection = event.shiftKey || event.metaKey || event.ctrlKey;
        if (!additiveSelection) {
          setSelectedItem(null);
        }
        const points = [point];
        dragRef.current = {
          type: "lasso",
          points,
          previousItemIds: additiveSelection ? selectedItems : [],
        };
        setLassoPoints(points);
        return;
      }
      if (tool === "pan") {
        setSelectedItem(null);
        dragRef.current = {
          type: "pan",
          startClientX: event.clientX,
          startClientY: event.clientY,
          origin: layoutRef.current.viewport,
        };
      }
    },
    [
      addCard,
      addFrame,
      addShape,
      addText,
      penColor,
      penWidth,
      pointFromEvent,
      pushUndoSnapshot,
      selected,
      selectedItems,
      setSelectedItem,
      strokePointFromEvent,
      tool,
    ],
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
        const point = strokePointFromEvent(event);
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
      if (drag.type === "eraser") {
        const point = pointFromEvent(event);
        setLocalLayout((current) => eraseStrokesAtPoint(current, point));
        return;
      }
      if (drag.type === "marquee") {
        const current = pointFromEvent(event);
        const rect = normaliseRect(drag.start, current);
        dragRef.current = { ...drag, current };
        setMarquee(rect);
        const nextSelection = selectedIdsFromMarquee(rect, layoutRef.current, positionedNodes);
        setSelectedItems(mergeSelectionIds(drag.previousItemIds, nextSelection));
        return;
      }
      if (drag.type === "lasso") {
        const point = pointFromEvent(event);
        const previous = drag.points[drag.points.length - 1];
        if (previous && Math.hypot(point.x - previous.x, point.y - previous.y) < 2) return;
        const points = [...drag.points, point];
        dragRef.current = { ...drag, points };
        setLassoPoints(points);
        const nextSelection = selectedIdsFromLasso(points, layoutRef.current, positionedNodes);
        setSelectedItems(mergeSelectionIds(drag.previousItemIds, nextSelection));
        return;
      }
      if (drag.type === "resize") {
        const point = pointFromEvent(event);
        const dx = point.x - drag.start.x;
        const dy = point.y - drag.start.y;
        const bounds = resizedBounds(drag.origin, drag.itemKind, drag.handle, dx, dy);
        setLocalLayout((current) => resizeLayoutItem(current, drag.itemId, drag.itemKind, bounds));
        return;
      }

      const point = pointFromEvent(event);
      const dx = point.x - drag.start.x;
      const dy = point.y - drag.start.y;
      if (drag.type === "multi") {
        setLocalLayout(() => translateSelectedLayout(drag.origin, drag.itemIds, dx, dy));
      } else if (drag.type === "node") {
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
      } else if (drag.type === "source") {
        setLocalLayout((current) => ({
          ...current,
          sources: current.sources.map((source) =>
            source.id === drag.sourceId
              ? { ...source, x: drag.origin.x + dx, y: drag.origin.y + dy }
              : source,
          ),
        }));
      }
    },
    [pointFromEvent, positionedNodes, setLocalLayout, strokePointFromEvent, updateViewport],
  );

  const handlePointerUp = useCallback(() => {
    if (!dragRef.current) return;
    const drag = dragRef.current;
    dragRef.current = null;
    if (drag.type === "marquee") {
      setMarquee(null);
      const rect = normaliseRect(drag.start, drag.current);
      if (rect.width < 3 && rect.height < 3) {
        setSelectedItems(drag.previousItemIds);
      }
      return;
    }
    if (drag.type === "lasso") {
      setLassoPoints([]);
      const bounds = boundsFromPoints("lasso", drag.points);
      if (!bounds || (bounds.width < 3 && bounds.height < 3) || drag.points.length < 3) {
        setSelectedItems(drag.previousItemIds);
      }
      return;
    }
    if (
      drag.type === "pan" ||
      drag.type === "stroke" ||
      drag.type === "eraser" ||
      drag.type === "multi" ||
      drag.type === "node" ||
      drag.type === "card" ||
      drag.type === "shape" ||
      drag.type === "frame" ||
      drag.type === "source" ||
      drag.type === "text" ||
      drag.type === "resize"
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
    if (selectedItems.length === 0 || !canDeleteSelected) return;
    pushUndoSnapshot();
    const selected = new Set(selectedItems);
    const nextLayout = {
      ...layoutRef.current,
      cards: layoutRef.current.cards.filter((card) => !selected.has(card.id)),
      shapes: layoutRef.current.shapes.filter((shape) => !selected.has(shape.id)),
      frames: layoutRef.current.frames.filter((frame) => !selected.has(frame.id)),
      texts: layoutRef.current.texts.filter((text) => !selected.has(text.id)),
      sources: layoutRef.current.sources.filter((source) => !selected.has(source.id)),
      strokes: layoutRef.current.strokes.filter((stroke) => !selected.has(stroke.id)),
      connectors: layoutRef.current.connectors.filter(
        (connector) =>
          !selected.has(connector.id) &&
          (connector.source_id === null || !selected.has(connector.source_id)) &&
          (connector.target_id === null || !selected.has(connector.target_id)),
      ),
    };
    setSelectedItem(null);
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [canDeleteSelected, commitLayout, pushUndoSnapshot, selectedItems, setSelectedItem]);

  const toggleSelectedLock = useCallback(() => {
    if (selectedItems.length === 0 || !canLockSelected) return;
    pushUndoSnapshot();
    const selected = new Set(selectedItems);
    const nextLocked = !selectedItemLocked;
    const nextLayout = {
      ...layoutRef.current,
      cards: layoutRef.current.cards.map((card) =>
        selected.has(card.id) ? { ...card, locked: nextLocked } : card,
      ),
      shapes: layoutRef.current.shapes.map((shape) =>
        selected.has(shape.id) ? { ...shape, locked: nextLocked } : shape,
      ),
      frames: layoutRef.current.frames.map((frame) =>
        selected.has(frame.id) ? { ...frame, locked: nextLocked } : frame,
      ),
      texts: layoutRef.current.texts.map((text) =>
        selected.has(text.id) ? { ...text, locked: nextLocked } : text,
      ),
      sources: layoutRef.current.sources.map((source) =>
        selected.has(source.id) ? { ...source, locked: nextLocked } : source,
      ),
      strokes: layoutRef.current.strokes.map((stroke) =>
        selected.has(stroke.id) ? { ...stroke, locked: nextLocked } : stroke,
      ),
      connectors: layoutRef.current.connectors.map((connector) =>
        selected.has(connector.id) ? { ...connector, locked: nextLocked } : connector,
      ),
    };
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [canLockSelected, commitLayout, pushUndoSnapshot, selectedItemLocked, selectedItems]);

  const arrangeSelected = useCallback((action: LayerAction) => {
    if (selectedItems.length === 0 || !canArrangeSelected) return;
    pushUndoSnapshot();
    const nextLayout = arrangeLayoutItems(layoutRef.current, selectedItems, action);
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [canArrangeSelected, commitLayout, pushUndoSnapshot, selectedItems]);

  const duplicateSelected = useCallback(() => {
    if (selectedItems.length === 0 || !canDuplicateSelected) return;
    pushUndoSnapshot();
    const offset = 32;
    const nextSelectedItems: string[] = [];
    const current = layoutRef.current;
    const nextLayout = cloneLayout(current);
    let nextZIndex = nextLayerIndex(current);

    for (const itemId of selectedItems) {
      const card = current.cards.find((candidate) => candidate.id === itemId);
      if (card) {
        const duplicate = { ...card, id: createId("card"), x: card.x + offset, y: card.y + offset, z_index: nextZIndex++ };
        nextLayout.cards.push(duplicate);
        nextSelectedItems.push(duplicate.id);
        continue;
      }

      const shape = current.shapes.find((candidate) => candidate.id === itemId);
      if (shape) {
        const duplicate = { ...shape, id: createId("shape"), x: shape.x + offset, y: shape.y + offset, z_index: nextZIndex++ };
        nextLayout.shapes.push(duplicate);
        nextSelectedItems.push(duplicate.id);
        continue;
      }

      const frame = current.frames.find((candidate) => candidate.id === itemId);
      if (frame) {
        const duplicate = { ...frame, id: createId("frame"), x: frame.x + offset, y: frame.y + offset, z_index: nextZIndex++ };
        nextLayout.frames.push(duplicate);
        nextSelectedItems.push(duplicate.id);
        continue;
      }

      const text = current.texts.find((candidate) => candidate.id === itemId);
      if (text) {
        const duplicate = { ...text, id: createId("text"), x: text.x + offset, y: text.y + offset, z_index: nextZIndex++ };
        nextLayout.texts.push(duplicate);
        nextSelectedItems.push(duplicate.id);
        continue;
      }

      const source = current.sources.find((candidate) => candidate.id === itemId);
      if (source) {
        const duplicate = { ...source, id: createId("source"), x: source.x + offset, y: source.y + offset, z_index: nextZIndex++ };
        nextLayout.sources.push(duplicate);
        nextSelectedItems.push(duplicate.id);
        continue;
      }

      const stroke = current.strokes.find((candidate) => candidate.id === itemId);
      if (stroke) {
        const duplicate = {
          ...stroke,
          id: createId("stroke"),
          points: stroke.points.map((point) => ({ ...point, x: point.x + offset, y: point.y + offset })),
          z_index: nextZIndex++,
        };
        nextLayout.strokes.push(duplicate);
        nextSelectedItems.push(duplicate.id);
      }
    }

    if (nextSelectedItems.length === 0) return;
    setSelectedItems(nextSelectedItems);
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [canDuplicateSelected, commitLayout, pushUndoSnapshot, selectedItems]);

  const setZoom = useCallback(
    (nextZoom: number) => {
      updateViewport({ ...layoutRef.current.viewport, zoom: clamp(nextZoom, MIN_ZOOM, MAX_ZOOM) }, true);
    },
    [updateViewport],
  );

  const resetView = useCallback(() => {
    updateViewport({ ...DEFAULT_VIEWPORT }, true);
  }, [updateViewport]);

  const handleViewportKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (isEditableElement(event.target)) return;
      const key = event.key.toLowerCase();
      const command = event.metaKey || event.ctrlKey;

      if (command && key === "a") {
        event.preventDefault();
        setSelectedItems(layoutItemBounds(layoutRef.current, positionedNodes).map((item) => item.id));
        setPendingConnector(null);
        return;
      }
      if (command && key === "d") {
        event.preventDefault();
        duplicateSelected();
        return;
      }
      if (command && key === "z") {
        event.preventDefault();
        if (event.shiftKey) {
          redoLayout();
        } else {
          undoLayout();
        }
        return;
      }
      if (key === "delete" || key === "backspace") {
        event.preventDefault();
        deleteSelected();
        return;
      }
      if (key === "escape") {
        event.preventDefault();
        setSelectedItem(null);
        setPendingConnector(null);
        setMarquee(null);
        setLassoPoints([]);
        dragRef.current = null;
        return;
      }
      if (key === "v") {
        setTool("select");
        setPendingConnector(null);
        return;
      }
      if (key === "h") {
        setTool("pan");
        setPendingConnector(null);
      }
    },
    [deleteSelected, duplicateSelected, positionedNodes, redoLayout, setSelectedItem, undoLayout],
  );

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
              <button type="button" disabled={!selected || unpinnedProjectionSources.length === 0} onClick={pinProjectionSources}>
                {copy.pinSources}
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
            {tool === "draw" ? (
              <div className="scheme-board__draw-settings" aria-label="Pen settings">
                <div className="scheme-board__swatches">
                  {PEN_COLORS.map((color) => (
                    <button
                      key={color}
                      type="button"
                      className={penColor === color ? "scheme-board__swatch scheme-board__swatch--active" : "scheme-board__swatch"}
                      style={{ background: color }}
                      aria-label={`Pen color ${color}`}
                      aria-pressed={penColor === color}
                      onClick={() => setPenColor(color)}
                    />
                  ))}
                </div>
                <input
                  type="range"
                  min={PEN_WIDTHS[0]}
                  max={PEN_WIDTHS[PEN_WIDTHS.length - 1]}
                  step="1"
                  value={penWidth}
                  aria-label="Pen width"
                  onChange={(event) => setPenWidth(Number(event.target.value))}
                />
              </div>
            ) : null}
            {pendingConnector ? <span>{copy.connectorHint}</span> : null}
          </div>

          {selected ? (
            <div
              ref={viewportRef}
              className={`scheme-board__viewport scheme-board__viewport--${tool}`}
              tabIndex={0}
              onPointerDown={handleViewportPointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerUp}
              onKeyDown={handleViewportKeyDown}
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
                          selectedItemSet.has(connector.id) ? "scheme-board__connector--selected" : "",
                          connector.locked ? "scheme-board__item--locked" : "",
                        ].filter(Boolean).join(" ")}
                        points={points.map((point) => `${point.x},${point.y}`).join(" ")}
                        stroke={connector.color}
                        onPointerDown={(event) => selectBoardItem(event, connector.id)}
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
                    <path
                      className={[
                        selectedItemSet.has(stroke.id) ? "scheme-board__stroke--selected" : "",
                        stroke.locked ? "scheme-board__item--locked" : "",
                      ].filter(Boolean).join(" ")}
                      d={strokePath(stroke.points)}
                      stroke={stroke.color}
                      strokeWidth={stroke.width}
                      strokeOpacity={stroke.opacity}
                      fill="none"
                      style={{ strokeWidth: stroke.width }}
                      onPointerDown={(event) => selectBoardItem(event, stroke.id)}
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
                        selectedItemSet.has(shape.id) ? "scheme-board__shape--selected" : "",
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
                      selectedItemSet.has(frame.id) ? "scheme-frame--selected" : "",
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
                      onPointerDown={(event) => selectBoardItem(event, frame.id)}
                      onMouseDown={(event) => selectBoardItem(event, frame.id)}
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
                      selectedItemSet.has(text.id) ? "scheme-text--selected" : "",
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
                      onPointerDown={(event) => selectBoardItem(event, text.id)}
                      onMouseDown={(event) => selectBoardItem(event, text.id)}
                      onFocus={() => beginInlineEdit(text.id)}
                      onChange={(event) => handleTextBlockChange(text.id, event.target.value)}
                      onBlur={finishInlineEdit}
                    />
                  </div>
                ))}

                {layout.sources.map((source) => (
                  <button
                    key={source.id}
                    type="button"
                    data-scheme-board-item="true"
                    className={[
                      "scheme-source",
                      `scheme-source--${source.source_kind}`,
                      selectedItemSet.has(source.id) ? "scheme-source--selected" : "",
                      source.locked ? "scheme-board__item--locked" : "",
                    ].filter(Boolean).join(" ")}
                    style={{
                      left: source.x,
                      top: source.y,
                      width: source.width,
                      height: source.height,
                      backgroundColor: source.color,
                      zIndex: layerZIndex(source.z_index),
                    }}
                    aria-label={`${source.source_kind} source ${source.title}`}
                    onPointerDown={(event) =>
                      handleItemPointerDown(event, { id: source.id, kind: "source" }, { x: source.x, y: source.y })
                    }
                  >
                    <span>{source.source_kind}</span>
                    <strong>{source.title}</strong>
                    {source.subtitle ? <small>{source.subtitle}</small> : null}
                    {source.excerpt ? <p>{source.excerpt}</p> : null}
                  </button>
                ))}

                {positionedNodes.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    data-scheme-board-item="true"
                    className={`scheme-node scheme-node--${node.kind} ${selectedItemSet.has(node.id) ? "scheme-node--selected" : ""}`}
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
                      selectedItemSet.has(card.id) ? "scheme-sticky--selected" : "",
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
                      onPointerDown={(event) => selectBoardItem(event, card.id)}
                      onMouseDown={(event) => selectBoardItem(event, card.id)}
                      onFocus={() => beginInlineEdit(card.id)}
                      onChange={(event) => handleCardTextChange(card.id, event.target.value)}
                      onBlur={finishInlineEdit}
                    />
                  </div>
                ))}
                {selectedResizable ? (
                  <div
                    className="scheme-board__resize-frame"
                    style={{
                      left: selectedResizable.bounds.x,
                      top: selectedResizable.bounds.y,
                      width: selectedResizable.bounds.width,
                      height: selectedResizable.bounds.height,
                      zIndex: 1_000_002 + layerZIndex(selectedResizable.zIndex),
                    }}
                    aria-hidden="true"
                  >
                    {RESIZE_HANDLES.map((handle) => (
                      <span
                        key={handle}
                        className={`scheme-board__resize-handle scheme-board__resize-handle--${handle}`}
                        data-scheme-resize-item={selectedResizable.bounds.id}
                        data-scheme-resize-handle={handle}
                        onPointerDown={(event) =>
                          handleResizePointerDown(
                            event,
                            selectedResizable.bounds.id,
                            selectedResizable.kind,
                            handle,
                          )
                        }
                      />
                    ))}
                  </div>
                ) : null}
                {marquee ? (
                  <div
                    className="scheme-board__marquee"
                    style={{
                      left: marquee.x,
                      top: marquee.y,
                      width: marquee.width,
                      height: marquee.height,
                    }}
                  />
                ) : null}
                {lassoPoints.length > 1 ? (
                  <svg className="scheme-board__lasso" aria-hidden="true">
                    <path d={lassoPath(lassoPoints)} />
                  </svg>
                ) : null}
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
