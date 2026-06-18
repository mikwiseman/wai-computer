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
  SchemeCanvasComment,
  SchemeCanvasFrame,
  SchemeCanvasLayout,
  SchemeCanvasShape,
  SchemeCanvasSourceBlock,
  SchemeConnector,
  SchemeFacilitationState,
  SchemeNode,
  SchemePosition,
  SchemeProjection,
  SchemeShapeKind,
  SchemeStroke,
  SchemeStrokeKind,
  SchemeStrokePoint,
  SchemeTimerState,
  SchemeTextBlock,
  SchemeViewport,
  SchemeVote,
  SchemeVotingSession,
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
  | "connector"
  | "comment";
type BoardItemKind = "node" | "card" | "shape" | "frame" | "text" | "source" | "comment";
type ResizableItemKind = Exclude<BoardItemKind, "node" | "comment">;
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

interface BoardBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface BoardViewportSize {
  width: number;
  height: number;
}

type BoardOutlineKind =
  | "node"
  | "sticky"
  | "source"
  | "frame"
  | "text"
  | "shape"
  | "drawing"
  | "connector"
  | "comment";

interface BoardOutlineItem {
  id: string;
  kind: BoardOutlineKind;
  label: string;
  detail: string;
  bounds: BoardItemBounds;
  order: number;
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
      type: "comment";
      commentId: string;
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

const SCHEME_LAYOUT_VERSION = 12 as const;
const DEFAULT_VIEWPORT: SchemeViewport = { x: 0, y: 0, zoom: 1 };
const MIN_TIMER_SECONDS = 60;
const DEFAULT_TIMER_SECONDS = 300;
const MAX_TIMER_SECONDS = 604_800;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2.8;
const FRAME_FOCUS_PADDING = 96;
const BOARD_FIT_PADDING = 112;
const OVERVIEW_WIDTH = 200;
const OVERVIEW_HEIGHT = 140;
const OVERVIEW_PADDING = 10;
const DEFAULT_GRID_SIZE = 40;
const MIN_GRID_SIZE = 8;
const MAX_GRID_SIZE = 240;
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
const COMMENT_PIN_SIZE = 34;
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
  { id: "comment", label: "Comment", ru: "Комментарий" },
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
    snapToGrid: "Snap to grid",
    gridSize: "Grid size",
    frames: "Frames",
    previousFrame: "Previous frame",
    nextFrame: "Next frame",
    previousSlide: "Previous slide",
    nextSlide: "Next slide",
    startPresentation: "Start presentation",
    exitPresentation: "Exit presentation",
    presenting: (index: number, total: number) => `Presenting ${index} / ${total}`,
    fitBoard: "Fit board",
    overview: "Board overview",
    outline: "Board outline",
    outlineEmpty: "No board objects yet.",
    outlineKinds: {
      node: "Node",
      sticky: "Sticky",
      source: "Source",
      frame: "Frame",
      text: "Text",
      shape: "Shape",
      drawing: "Drawing",
      connector: "Connector",
      comment: "Comment",
    },
    comments: "Comments",
    commentsEmpty: "No comments yet.",
    unresolvedComments: (count: number) => `${count} open`,
    commentText: "Comment text",
    resolveComment: "Resolve comment",
    reopenComment: "Reopen comment",
    resolvedComment: "resolved",
    defaultCommentText: "Comment",
    facilitation: "Facilitation",
    voting: "Voting",
    vote: "Vote",
    votes: (count: number) => `${count} vote${count === 1 ? "" : "s"}`,
    startVote: "Start vote",
    addVote: "Add vote",
    endVote: "End vote",
    clearVote: "Clear votes",
    voteScope: (count: number) => `${count} objects`,
    noVoteTarget: "Select an object to vote.",
    timer: "Timer",
    startTimer: "Start timer",
    pauseTimer: "Pause timer",
    stopTimer: "Stop timer",
    addMinute: "+1 min",
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
    snapToGrid: "Привязка к сетке",
    gridSize: "Размер сетки",
    frames: "Фреймы",
    previousFrame: "Предыдущий фрейм",
    nextFrame: "Следующий фрейм",
    previousSlide: "Предыдущий слайд",
    nextSlide: "Следующий слайд",
    startPresentation: "Начать презентацию",
    exitPresentation: "Закрыть презентацию",
    presenting: (index: number, total: number) => `Презентация ${index} / ${total}`,
    fitBoard: "Вся доска",
    overview: "Обзор доски",
    outline: "Структура доски",
    outlineEmpty: "На доске пока нет объектов.",
    outlineKinds: {
      node: "Узел",
      sticky: "Стикер",
      source: "Источник",
      frame: "Фрейм",
      text: "Текст",
      shape: "Фигура",
      drawing: "Рисунок",
      connector: "Связь",
      comment: "Комментарий",
    },
    comments: "Комментарии",
    commentsEmpty: "Комментариев пока нет.",
    unresolvedComments: (count: number) => `${count} открыт.`,
    commentText: "Текст комментария",
    resolveComment: "Закрыть комментарий",
    reopenComment: "Открыть комментарий",
    resolvedComment: "закрыт",
    defaultCommentText: "Комментарий",
    facilitation: "Фасилитация",
    voting: "Голосование",
    vote: "Голос",
    votes: (count: number) => `${count} голос.`,
    startVote: "Начать голосование",
    addVote: "Добавить голос",
    endVote: "Завершить",
    clearVote: "Очистить голоса",
    voteScope: (count: number) => `${count} объект.`,
    noVoteTarget: "Выберите объект для голоса.",
    timer: "Таймер",
    startTimer: "Запустить таймер",
    pauseTimer: "Пауза",
    stopTimer: "Сбросить",
    addMinute: "+1 мин",
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

function normaliseGridSize(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value)
    ? clamp(value, MIN_GRID_SIZE, MAX_GRID_SIZE)
    : DEFAULT_GRID_SIZE;
}

function snapValue(value: number, gridSize: number): number {
  return Math.round(value / gridSize) * gridSize;
}

function snapPosition(position: SchemePosition, layout: SchemeCanvasLayout): SchemePosition {
  const gridSize = normaliseGridSize(layout.grid_size);
  return {
    x: snapValue(position.x, gridSize),
    y: snapValue(position.y, gridSize),
  };
}

function positionForNewItem(
  point: SchemePosition,
  width: number,
  height: number,
  layout: SchemeCanvasLayout,
  shouldSnap: boolean,
): SchemePosition {
  const position = { x: point.x - width / 2, y: point.y - height / 2 };
  return shouldSnap ? snapPosition(position, layout) : position;
}

function normaliseFrameOrder(frames: SchemeCanvasFrame[], frameOrder: unknown): string[] {
  const frameIds = frames.map((frame) => frame.id);
  const frameIdSet = new Set(frameIds);
  const ordered = Array.isArray(frameOrder)
    ? frameOrder.filter((id): id is string => typeof id === "string" && frameIdSet.has(id))
    : [];
  const seen = new Set<string>();
  const uniqueOrdered = ordered.filter((id) => {
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  return [...uniqueOrdered, ...frameIds.filter((id) => !seen.has(id))];
}

function orderedFramesForLayout(layout: SchemeCanvasLayout): SchemeCanvasFrame[] {
  const frameById = new Map(layout.frames.map((frame) => [frame.id, frame]));
  return normaliseFrameOrder(layout.frames, layout.frame_order).flatMap((id) => {
    const frame = frameById.get(id);
    return frame ? [frame] : [];
  });
}

function normalisePresentation(
  presentation: Partial<SchemeCanvasLayout["presentation"]> | null | undefined,
  frames: SchemeCanvasFrame[],
): SchemeCanvasLayout["presentation"] {
  const frameIds = new Set(frames.map((frame) => frame.id));
  const frameId = typeof presentation?.frame_id === "string" && frameIds.has(presentation.frame_id)
    ? presentation.frame_id
    : null;
  const active = Boolean(presentation?.active) && frameId !== null;
  return {
    active,
    frame_id: active ? frameId : null,
  };
}

function blankVotingSession(): SchemeVotingSession {
  return {
    active: false,
    title: "Vote",
    votes_per_person: 3,
    one_vote_per_object: false,
    show_results: true,
    selected_item_ids: [],
    votes: [],
  };
}

function blankTimerState(): SchemeTimerState {
  return {
    active: false,
    duration_seconds: DEFAULT_TIMER_SECONDS,
    started_at_ms: null,
    paused_remaining_seconds: null,
  };
}

function blankFacilitation(): SchemeFacilitationState {
  return {
    voting: blankVotingSession(),
    timer: blankTimerState(),
  };
}

function uniqueStrings(values: unknown): string[] {
  if (!Array.isArray(values)) return [];
  return Array.from(new Set(values.filter((value): value is string => typeof value === "string" && value.length > 0)));
}

function normaliseVote(vote: Partial<SchemeVote> | null | undefined): SchemeVote | null {
  if (!vote || typeof vote.item_id !== "string" || vote.item_id.length === 0) return null;
  if (typeof vote.count !== "number" || !Number.isFinite(vote.count)) return null;
  return {
    item_id: vote.item_id,
    count: Math.max(0, Math.floor(vote.count)),
  };
}

function normaliseVoting(voting: Partial<SchemeVotingSession> | null | undefined): SchemeVotingSession {
  const base = blankVotingSession();
  const votes = Array.isArray(voting?.votes)
    ? voting.votes.flatMap((vote) => {
        const normalised = normaliseVote(vote);
        return normalised ? [normalised] : [];
      })
    : [];
  const votesByItem = new Map<string, SchemeVote>();
  votes.forEach((vote) => {
    votesByItem.set(vote.item_id, vote);
  });
  return {
    active: Boolean(voting?.active),
    title: typeof voting?.title === "string" && voting.title.trim() ? voting.title : base.title,
    votes_per_person:
      typeof voting?.votes_per_person === "number" && Number.isFinite(voting.votes_per_person)
        ? clamp(Math.floor(voting.votes_per_person), 1, 99)
        : base.votes_per_person,
    one_vote_per_object: Boolean(voting?.one_vote_per_object),
    show_results: voting?.show_results ?? base.show_results,
    selected_item_ids: uniqueStrings(voting?.selected_item_ids),
    votes: Array.from(votesByItem.values()).filter((vote) => vote.count > 0),
  };
}

function normaliseTimer(timer: Partial<SchemeTimerState> | null | undefined): SchemeTimerState {
  const durationSeconds =
    typeof timer?.duration_seconds === "number" && Number.isFinite(timer.duration_seconds)
      ? clamp(Math.floor(timer.duration_seconds), MIN_TIMER_SECONDS, MAX_TIMER_SECONDS)
      : DEFAULT_TIMER_SECONDS;
  const startedAtMs =
    typeof timer?.started_at_ms === "number" && Number.isFinite(timer.started_at_ms)
      ? Math.floor(timer.started_at_ms)
      : null;
  const pausedRemainingSeconds =
    typeof timer?.paused_remaining_seconds === "number" && Number.isFinite(timer.paused_remaining_seconds)
      ? clamp(Math.floor(timer.paused_remaining_seconds), 0, MAX_TIMER_SECONDS)
      : null;
  return {
    active: Boolean(timer?.active) && startedAtMs !== null,
    duration_seconds: durationSeconds,
    started_at_ms: Boolean(timer?.active) && startedAtMs !== null ? startedAtMs : null,
    paused_remaining_seconds: Boolean(timer?.active) ? null : pausedRemainingSeconds,
  };
}

function normaliseFacilitation(
  facilitation: Partial<SchemeFacilitationState> | null | undefined,
): SchemeFacilitationState {
  return {
    voting: normaliseVoting(facilitation?.voting),
    timer: normaliseTimer(facilitation?.timer),
  };
}

function cloneFacilitation(facilitation: SchemeFacilitationState): SchemeFacilitationState {
  return {
    voting: {
      ...facilitation.voting,
      selected_item_ids: [...facilitation.voting.selected_item_ids],
      votes: facilitation.voting.votes.map((vote) => ({ ...vote })),
    },
    timer: { ...facilitation.timer },
  };
}

function timerRemainingSeconds(timer: SchemeTimerState, nowMs: number): number {
  if (!timer.active || timer.started_at_ms === null) {
    return timer.paused_remaining_seconds ?? timer.duration_seconds;
  }
  const elapsedSeconds = Math.max(0, Math.floor((nowMs - timer.started_at_ms) / 1000));
  return Math.max(0, timer.duration_seconds - elapsedSeconds);
}

function formatTimer(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.max(0, seconds % 60);
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function viewportForFrame(frame: SchemeCanvasFrame, rect: DOMRect): SchemeViewport {
  const availableWidth = Math.max(1, rect.width - FRAME_FOCUS_PADDING);
  const availableHeight = Math.max(1, rect.height - FRAME_FOCUS_PADDING);
  const zoom = clamp(
    Math.min(availableWidth / frame.width, availableHeight / frame.height),
    MIN_ZOOM,
    MAX_ZOOM,
  );
  const centerX = frame.x + frame.width / 2;
  const centerY = frame.y + frame.height / 2;
  return {
    x: -centerX * zoom,
    y: -centerY * zoom,
    zoom,
  };
}

function viewportForBounds(bounds: BoardBounds, rect: DOMRect): SchemeViewport {
  const availableWidth = Math.max(1, rect.width - BOARD_FIT_PADDING);
  const availableHeight = Math.max(1, rect.height - BOARD_FIT_PADDING);
  const zoom = clamp(
    Math.min(availableWidth / Math.max(1, bounds.width), availableHeight / Math.max(1, bounds.height)),
    MIN_ZOOM,
    MAX_ZOOM,
  );
  return {
    x: -(bounds.x + bounds.width / 2) * zoom,
    y: -(bounds.y + bounds.height / 2) * zoom,
    zoom,
  };
}

function viewportForFocusedBounds(
  bounds: BoardItemBounds,
  rect: DOMRect,
  currentZoom: number,
): SchemeViewport {
  const availableWidth = Math.max(1, rect.width - BOARD_FIT_PADDING);
  const availableHeight = Math.max(1, rect.height - BOARD_FIT_PADDING);
  const clampedCurrentZoom = clamp(currentZoom, MIN_ZOOM, MAX_ZOOM);
  const fitsAtCurrentZoom =
    bounds.width * clampedCurrentZoom <= availableWidth &&
    bounds.height * clampedCurrentZoom <= availableHeight;
  const zoom = fitsAtCurrentZoom
    ? clampedCurrentZoom
    : clamp(
        Math.min(availableWidth / Math.max(1, bounds.width), availableHeight / Math.max(1, bounds.height)),
        MIN_ZOOM,
        MAX_ZOOM,
      );
  return {
    x: -(bounds.x + bounds.width / 2) * zoom,
    y: -(bounds.y + bounds.height / 2) * zoom,
    zoom,
  };
}

function blankLayout(): SchemeCanvasLayout {
  return {
    version: SCHEME_LAYOUT_VERSION,
    snap_to_grid: false,
    grid_size: DEFAULT_GRID_SIZE,
    viewport: { ...DEFAULT_VIEWPORT },
    presentation: { active: false, frame_id: null },
    node_positions: {},
    strokes: [],
    cards: [],
    shapes: [],
    frames: [],
    frame_order: [],
    texts: [],
    sources: [],
    connectors: [],
    comments: [],
    facilitation: blankFacilitation(),
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

function normaliseComment(comment: SchemeCanvasComment): SchemeCanvasComment {
  return {
    ...comment,
    text: comment.text,
    resolved: comment.resolved ?? false,
  };
}

function layoutForScheme(scheme: Scheme | null): SchemeCanvasLayout {
  const raw = scheme?.layout as Partial<SchemeCanvasLayout> | null;
  if (!raw) return blankLayout();
  const maybeLegacy = raw as unknown as Record<string, unknown>;
  if (!("version" in maybeLegacy) && Object.values(maybeLegacy).every(isPosition)) {
    return { ...blankLayout(), node_positions: maybeLegacy as Record<string, SchemePosition> };
  }
  const nextLayout = normaliseLayoutLayers({
    ...blankLayout(),
    ...raw,
    version: SCHEME_LAYOUT_VERSION,
    snap_to_grid: Boolean(raw.snap_to_grid),
    grid_size: normaliseGridSize(raw.grid_size),
    viewport: { ...DEFAULT_VIEWPORT, ...(raw.viewport ?? {}) },
    presentation: { active: false, frame_id: null },
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
    comments: (raw.comments ?? []).map(normaliseComment),
    facilitation: normaliseFacilitation(raw.facilitation),
  });
  return {
    ...nextLayout,
    frame_order: normaliseFrameOrder(nextLayout.frames, raw.frame_order),
    presentation: normalisePresentation(raw.presentation, nextLayout.frames),
  };
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

function canDeleteLayoutItem(itemId: string | null, layout: SchemeCanvasLayout): boolean {
  if (!itemId) return false;
  return canLockLayoutItem(itemId, layout) || layout.comments.some((candidate) => candidate.id === itemId);
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

function contentBoundsForItems(items: BoardItemBounds[]): BoardBounds | null {
  if (items.length === 0) return null;
  const minX = Math.min(...items.map((item) => item.x));
  const minY = Math.min(...items.map((item) => item.y));
  const maxX = Math.max(...items.map((item) => item.x + Math.max(1, item.width)));
  const maxY = Math.max(...items.map((item) => item.y + Math.max(1, item.height)));
  return {
    x: minX,
    y: minY,
    width: Math.max(1, maxX - minX),
    height: Math.max(1, maxY - minY),
  };
}

function overviewMetrics(bounds: BoardBounds, width: number, height: number) {
  const availableWidth = Math.max(1, width - OVERVIEW_PADDING * 2);
  const availableHeight = Math.max(1, height - OVERVIEW_PADDING * 2);
  const scale = Math.min(
    availableWidth / Math.max(1, bounds.width),
    availableHeight / Math.max(1, bounds.height),
  );
  const scaledWidth = bounds.width * scale;
  const scaledHeight = bounds.height * scale;
  return {
    scale,
    originX: (width - scaledWidth) / 2,
    originY: (height - scaledHeight) / 2,
  };
}

function overviewItemStyle(item: BoardItemBounds, bounds: BoardBounds) {
  const metrics = overviewMetrics(bounds, OVERVIEW_WIDTH, OVERVIEW_HEIGHT);
  return {
    left: metrics.originX + (item.x - bounds.x) * metrics.scale,
    top: metrics.originY + (item.y - bounds.y) * metrics.scale,
    width: Math.max(2, item.width * metrics.scale),
    height: Math.max(2, item.height * metrics.scale),
  };
}

function overviewViewportStyle(
  viewport: SchemeViewport,
  viewportSize: BoardViewportSize,
  bounds: BoardBounds,
) {
  if (viewportSize.width <= 1 || viewportSize.height <= 1) return null;
  const metrics = overviewMetrics(bounds, OVERVIEW_WIDTH, OVERVIEW_HEIGHT);
  const zoom = Math.max(MIN_ZOOM, viewport.zoom);
  const worldViewport = {
    x: (-viewportSize.width / 2 - viewport.x) / zoom,
    y: (-viewportSize.height / 2 - viewport.y) / zoom,
    width: viewportSize.width / zoom,
    height: viewportSize.height / zoom,
  };
  return {
    left: metrics.originX + (worldViewport.x - bounds.x) * metrics.scale,
    top: metrics.originY + (worldViewport.y - bounds.y) * metrics.scale,
    width: Math.max(2, worldViewport.width * metrics.scale),
    height: Math.max(2, worldViewport.height * metrics.scale),
  };
}

function overviewPointFromEvent(
  clientX: number,
  clientY: number,
  rect: DOMRect,
  bounds: BoardBounds,
): SchemePosition {
  const metrics = overviewMetrics(bounds, rect.width, rect.height);
  return {
    x: bounds.x + (clientX - rect.left - metrics.originX) / metrics.scale,
    y: bounds.y + (clientY - rect.top - metrics.originY) / metrics.scale,
  };
}

function shortBoardLabel(value: string | null | undefined, fallback: string): string {
  const firstLine = (value ?? "").split("\n").map((line) => line.trim()).find(Boolean);
  if (!firstLine) return fallback;
  return firstLine.length > 64 ? `${firstLine.slice(0, 61)}...` : firstLine;
}

function boardOutlineItemsForLayout(
  layout: SchemeCanvasLayout,
  nodes: SchemeNode[],
  orderedFrames: SchemeCanvasFrame[],
): BoardOutlineItem[] {
  const items: BoardOutlineItem[] = [];
  const pushItem = (
    item: Omit<BoardOutlineItem, "order">,
  ) => {
    items.push({ ...item, order: items.length });
  };

  orderedFrames.forEach((frame) => {
    pushItem({
      id: frame.id,
      kind: "frame",
      label: shortBoardLabel(frame.title, "Untitled frame"),
      detail: `${Math.round(frame.width)} x ${Math.round(frame.height)}`,
      bounds: { id: frame.id, x: frame.x, y: frame.y, width: frame.width, height: frame.height },
    });
  });
  nodes.forEach((node) => {
    pushItem({
      id: node.id,
      kind: "node",
      label: shortBoardLabel(node.title, "Untitled node"),
      detail: nodeKindLabel(node.kind),
      bounds: { id: node.id, x: node.position.x, y: node.position.y, width: NODE_WIDTH, height: NODE_HEIGHT },
    });
  });
  layout.sources.forEach((source) => {
    pushItem({
      id: source.id,
      kind: "source",
      label: shortBoardLabel(source.title, "Untitled source"),
      detail: source.source_kind,
      bounds: { id: source.id, x: source.x, y: source.y, width: source.width, height: source.height },
    });
  });
  layout.cards.forEach((card) => {
    pushItem({
      id: card.id,
      kind: "sticky",
      label: shortBoardLabel(card.text, "Untitled sticky"),
      detail: card.locked ? "locked" : "sticky note",
      bounds: { id: card.id, x: card.x, y: card.y, width: card.width, height: card.height },
    });
  });
  layout.texts.forEach((text) => {
    pushItem({
      id: text.id,
      kind: "text",
      label: shortBoardLabel(text.text, "Untitled text"),
      detail: `${Math.round(text.font_size)}px`,
      bounds: { id: text.id, x: text.x, y: text.y, width: text.width, height: text.height },
    });
  });
  layout.shapes.forEach((shape) => {
    pushItem({
      id: shape.id,
      kind: "shape",
      label: shape.kind === "ellipse" ? "Oval" : "Box",
      detail: shape.locked ? "locked" : shape.kind,
      bounds: { id: shape.id, x: shape.x, y: shape.y, width: shape.width, height: shape.height },
    });
  });
  layout.strokes.forEach((stroke) => {
    const bounds = boundsFromPoints(stroke.id, stroke.points);
    if (!bounds) return;
    pushItem({
      id: stroke.id,
      kind: "drawing",
      label: stroke.kind === "highlighter" ? "Highlighter stroke" : "Pen stroke",
      detail: stroke.locked ? "locked" : `${stroke.points.length} points`,
      bounds,
    });
  });
  layout.connectors.forEach((connector) => {
    const source = itemCenter(connector.source_id, nodes, layout);
    const target = itemCenter(connector.target_id, nodes, layout);
    const points = source && target ? [source, target] : connector.points;
    const bounds = boundsFromPoints(connector.id, points);
    if (!bounds) return;
    pushItem({
      id: connector.id,
      kind: "connector",
      label: "Connector",
      detail: connector.locked ? "locked" : `${points.length} points`,
      bounds,
    });
  });
  layout.comments.forEach((comment) => {
    pushItem({
      id: comment.id,
      kind: "comment",
      label: shortBoardLabel(comment.text, "Comment"),
      detail: comment.resolved ? "resolved" : "open",
      bounds: {
        id: comment.id,
        x: comment.x - COMMENT_PIN_SIZE / 2,
        y: comment.y - COMMENT_PIN_SIZE / 2,
        width: COMMENT_PIN_SIZE,
        height: COMMENT_PIN_SIZE,
      },
    });
  });

  return items;
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
    ...layout.comments.map((comment) => ({
      id: comment.id,
      x: comment.x - COMMENT_PIN_SIZE / 2,
      y: comment.y - COMMENT_PIN_SIZE / 2,
      width: COMMENT_PIN_SIZE,
      height: COMMENT_PIN_SIZE,
    })),
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

function snapResizedBounds(
  origin: BoardItemBounds,
  kind: ResizableItemKind,
  handle: ResizeHandle,
  bounds: BoardItemBounds,
  layout: SchemeCanvasLayout,
): BoardItemBounds {
  const limits = RESIZE_LIMITS[kind];
  const gridSize = normaliseGridSize(layout.grid_size);
  let x = bounds.x;
  let y = bounds.y;
  let width = bounds.width;
  let height = bounds.height;

  if (handle.endsWith("w")) {
    const right = origin.x + origin.width;
    width = clamp(right - snapValue(bounds.x, gridSize), limits.minWidth, limits.maxWidth);
    x = right - width;
  } else {
    x = origin.x;
    width = clamp(snapValue(bounds.x + bounds.width, gridSize) - origin.x, limits.minWidth, limits.maxWidth);
  }

  if (handle.startsWith("n")) {
    const bottom = origin.y + origin.height;
    height = clamp(bottom - snapValue(bounds.y, gridSize), limits.minHeight, limits.maxHeight);
    y = bottom - height;
  } else {
    y = origin.y;
    height = clamp(snapValue(bounds.y + bounds.height, gridSize) - origin.y, limits.minHeight, limits.maxHeight);
  }

  return { id: origin.id, x, y, width, height };
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
    comments: layout.comments.map((comment) =>
      selected.has(comment.id) ? { ...comment, x: comment.x + dx, y: comment.y + dy } : comment,
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

function translatedNodesForLayout(nodes: SchemeNode[], layout: SchemeCanvasLayout): SchemeNode[] {
  return nodes.map((node) => ({
    ...node,
    position: layout.node_positions[node.id] ?? node.position,
  }));
}

function snapTranslatedSelectedLayout(
  origin: SchemeCanvasLayout,
  itemIds: string[],
  dx: number,
  dy: number,
  nodes: SchemeNode[],
  shouldSnap: boolean,
): SchemeCanvasLayout {
  const translated = translateSelectedLayout(origin, itemIds, dx, dy);
  if (!shouldSnap) return translated;

  const translatedNodes = translatedNodesForLayout(nodes, translated);
  const anchor = layoutItemBounds(translated, translatedNodes).find((bounds) => itemIds.includes(bounds.id));
  if (!anchor) return translated;

  const snapped = snapPosition({ x: anchor.x, y: anchor.y }, origin);
  return translateSelectedLayout(origin, itemIds, dx + snapped.x - anchor.x, dy + snapped.y - anchor.y);
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
    snap_to_grid: layout.snap_to_grid,
    grid_size: layout.grid_size,
    viewport: { ...layout.viewport },
    presentation: { ...normalisePresentation(layout.presentation, layout.frames) },
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
    frame_order: [...layout.frame_order],
    texts: layout.texts.map((text) => ({ ...text })),
    sources: layout.sources.map((source) => ({ ...source })),
    connectors: layout.connectors.map((connector) => ({
      ...connector,
      points: connector.points.map((point) => ({ ...point })),
    })),
    comments: layout.comments.map((comment) => ({ ...comment })),
    facilitation: cloneFacilitation(layout.facilitation),
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
  const [viewportSize, setViewportSize] = useState<BoardViewportSize>({ width: 0, height: 0 });
  const [nowMs, setNowMs] = useState(() => Date.now());
  const dragRef = useRef<DragState | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const selectedRef = useRef<Scheme | null>(null);
  const layoutRef = useRef<SchemeCanvasLayout>(layout);
  const wheelCommitRef = useRef<number | null>(null);
  const undoStackRef = useRef<SchemeCanvasLayout[]>([]);
  const redoStackRef = useRef<SchemeCanvasLayout[]>([]);
  const editingItemRef = useRef<string | null>(null);
  const commitSequenceRef = useRef(0);
  const pendingCommitRef = useRef<Promise<void>>(Promise.resolve());

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
    commitSequenceRef.current += 1;
    pendingCommitRef.current = Promise.resolve();
    setHistoryCounts({ undo: 0, redo: 0 });
  }, [selectedId, setSelectedItem]);

  useEffect(() => {
    const measureViewport = () => {
      const rect = viewportRef.current?.getBoundingClientRect();
      if (!rect) return;
      setViewportSize((current) => {
        if (current.width === rect.width && current.height === rect.height) return current;
        return { width: rect.width, height: rect.height };
      });
    };
    measureViewport();
    window.addEventListener("resize", measureViewport);
    return () => window.removeEventListener("resize", measureViewport);
  }, [selectedId]);

  useEffect(() => {
    if (!layout.facilitation.timer.active) return undefined;
    setNowMs(Date.now());
    const intervalId = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(intervalId);
  }, [layout.facilitation.timer.active]);

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
      selectedItems.every((itemId) => canDeleteLayoutItem(itemId, layout) && !isLayoutItemLocked(itemId, layout)),
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
  const boardItems = useMemo(() => layoutItemBounds(layout, positionedNodes), [layout, positionedNodes]);
  const boardItemIds = useMemo(() => new Set(boardItems.map((item) => item.id)), [boardItems]);
  const boardContentBounds = useMemo(() => contentBoundsForItems(boardItems), [boardItems]);
  const selectedVoteTargetId = useMemo(() => {
    const selectedTarget = selectedItems.find((itemId) => boardItemIds.has(itemId));
    if (selectedTarget) return selectedTarget;
    return layout.facilitation.voting.selected_item_ids.find((itemId) => boardItemIds.has(itemId)) ?? null;
  }, [boardItemIds, layout.facilitation.voting.selected_item_ids, selectedItems]);
  const voteTotal = useMemo(
    () => layout.facilitation.voting.votes.reduce((sum, vote) => sum + vote.count, 0),
    [layout.facilitation.voting.votes],
  );
  const voteScopeCount = useMemo(() => {
    const selectedScopeCount = layout.facilitation.voting.selected_item_ids.filter((itemId) =>
      boardItemIds.has(itemId),
    ).length;
    return selectedScopeCount > 0 ? selectedScopeCount : boardItems.length;
  }, [boardItemIds, boardItems.length, layout.facilitation.voting.selected_item_ids]);
  const voteBadges = useMemo(() => {
    if (!layout.facilitation.voting.show_results) return [];
    const boundsById = new Map(boardItems.map((item) => [item.id, item]));
    return layout.facilitation.voting.votes.flatMap((vote) => {
      const bounds = boundsById.get(vote.item_id);
      return bounds && vote.count > 0 ? [{ vote, bounds }] : [];
    });
  }, [boardItems, layout.facilitation.voting.show_results, layout.facilitation.voting.votes]);
  const remainingTimerSeconds = timerRemainingSeconds(layout.facilitation.timer, nowMs);
  const overviewViewport = useMemo(
    () => (boardContentBounds ? overviewViewportStyle(layout.viewport, viewportSize, boardContentBounds) : null),
    [boardContentBounds, layout.viewport, viewportSize],
  );
  const projectionSources = useMemo(() => projectionSourceSummaries(projection), [projection]);
  const unpinnedProjectionSources = useMemo(() => {
    const pinned = new Set(layout.sources.map((source) => source.citation_id));
    return projectionSources.filter((source) => !pinned.has(source.id));
  }, [layout.sources, projectionSources]);
  const orderedFrames = useMemo(() => orderedFramesForLayout(layout), [layout]);
  const boardOutlineItems = useMemo(
    () => boardOutlineItemsForLayout(layout, positionedNodes, orderedFrames),
    [layout, positionedNodes, orderedFrames],
  );
  const unresolvedCommentCount = useMemo(
    () => layout.comments.filter((comment) => !comment.resolved).length,
    [layout.comments],
  );
  const presentation = useMemo(
    () => normalisePresentation(layout.presentation, layout.frames),
    [layout.presentation, layout.frames],
  );
  const activeFrameIndex = useMemo(() => {
    if (selectedItems.length !== 1) return -1;
    return orderedFrames.findIndex((frame) => frame.id === selectedItems[0]);
  }, [orderedFrames, selectedItems]);
  const presentationFrameIndex = useMemo(() => {
    if (!presentation.active) return -1;
    return orderedFrames.findIndex((frame) => frame.id === presentation.frame_id);
  }, [orderedFrames, presentation]);
  const isPresenting = presentationFrameIndex >= 0;
  const presentationFrame = isPresenting ? orderedFrames[presentationFrameIndex] : null;
  const previousFrameLabel = isPresenting ? copy.previousSlide : copy.previousFrame;
  const nextFrameLabel = isPresenting ? copy.nextSlide : copy.nextFrame;

  const commitLayout = useCallback(
    (nextLayout: SchemeCanvasLayout) => {
      const schemeId = selectedRef.current?.id;
      if (!schemeId) return Promise.resolve();
      const sequence = ++commitSequenceRef.current;
      const task = pendingCommitRef.current
        .catch(() => undefined)
        .then(async () => {
          try {
            const updated = await updateScheme(schemeId, { layout: nextLayout });
            if (sequence === commitSequenceRef.current && selectedRef.current?.id === schemeId) {
              replaceScheme(updated);
            }
          } catch (err) {
            reportError(err, "Couldn't save scheme board.");
          }
        });
      pendingCommitRef.current = task;
      return task;
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

  const shouldSnapEvent = useCallback((event: PointerEvent<Element>): boolean => {
    return layoutRef.current.snap_to_grid && !event.metaKey && !event.ctrlKey;
  }, []);

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

  const focusFrame = useCallback(
    (frame: SchemeCanvasFrame) => {
      const rect = viewportRef.current?.getBoundingClientRect();
      if (!rect) return;
      const currentPresentation = normalisePresentation(layoutRef.current.presentation, layoutRef.current.frames);
      const nextLayout = {
        ...layoutRef.current,
        frame_order: normaliseFrameOrder(layoutRef.current.frames, layoutRef.current.frame_order),
        presentation: currentPresentation.active
          ? { active: true, frame_id: frame.id }
          : currentPresentation,
        viewport: viewportForFrame(frame, rect),
      };
      setSelectedItem(frame.id);
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout, setSelectedItem],
  );

  const focusAdjacentFrame = useCallback(
    (offset: number) => {
      const frames = orderedFramesForLayout(layoutRef.current);
      if (frames.length === 0) return;
      const currentPresentation = normalisePresentation(layoutRef.current.presentation, layoutRef.current.frames);
      const presentingFrameId = currentPresentation.active ? currentPresentation.frame_id : null;
      const currentIndex = presentingFrameId
        ? frames.findIndex((frame) => frame.id === presentingFrameId)
        : selectedItems.length === 1
        ? frames.findIndex((frame) => frame.id === selectedItems[0])
        : -1;
      const baseIndex = currentIndex === -1 ? (offset > 0 ? -1 : 0) : currentIndex;
      const nextIndex = (baseIndex + offset + frames.length) % frames.length;
      focusFrame(frames[nextIndex]);
    },
    [focusFrame, selectedItems],
  );

  const startPresentation = useCallback(() => {
    const frames = orderedFramesForLayout(layoutRef.current);
    const rect = viewportRef.current?.getBoundingClientRect();
    if (frames.length === 0 || !rect) return;
    const currentPresentation = normalisePresentation(layoutRef.current.presentation, layoutRef.current.frames);
    const selectedFrame = selectedItems.length === 1
      ? frames.find((frame) => frame.id === selectedItems[0])
      : undefined;
    const currentFrame = currentPresentation.frame_id
      ? frames.find((frame) => frame.id === currentPresentation.frame_id)
      : undefined;
    const frame = currentFrame ?? selectedFrame ?? frames[0];
    const nextLayout = {
      ...layoutRef.current,
      frame_order: normaliseFrameOrder(layoutRef.current.frames, layoutRef.current.frame_order),
      presentation: { active: true, frame_id: frame.id },
      viewport: viewportForFrame(frame, rect),
    };
    setSelectedItem(frame.id);
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [commitLayout, selectedItems, setSelectedItem]);

  const exitPresentation = useCallback(() => {
    const nextLayout = {
      ...layoutRef.current,
      presentation: { active: false, frame_id: null },
    };
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [commitLayout]);

  const advancePresentation = useCallback((offset: number) => {
    focusAdjacentFrame(offset);
  }, [focusAdjacentFrame]);

  const updateSnapToGrid = useCallback(
    (enabled: boolean) => {
      const nextLayout = {
        ...layoutRef.current,
        snap_to_grid: enabled,
        grid_size: normaliseGridSize(layoutRef.current.grid_size),
      };
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout],
  );

  const updateGridSize = useCallback(
    (value: number) => {
      const nextLayout = {
        ...layoutRef.current,
        grid_size: normaliseGridSize(value),
      };
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout],
  );

  const addCard = useCallback(
    (point: SchemePosition, shouldSnap: boolean) => {
      pushUndoSnapshot();
      const position = positionForNewItem(point, STICKY_WIDTH, STICKY_HEIGHT, layoutRef.current, shouldSnap);
      const card: SchemeCanvasCard = {
        id: createId("card"),
        x: position.x,
        y: position.y,
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
    (point: SchemePosition, kind: SchemeShapeKind, shouldSnap: boolean) => {
      pushUndoSnapshot();
      const position = positionForNewItem(point, SHAPE_WIDTH, SHAPE_HEIGHT, layoutRef.current, shouldSnap);
      const shape: SchemeCanvasShape = {
        id: createId("shape"),
        kind,
        x: position.x,
        y: position.y,
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
    (point: SchemePosition, shouldSnap: boolean) => {
      pushUndoSnapshot();
      const position = positionForNewItem(point, FRAME_WIDTH, FRAME_HEIGHT, layoutRef.current, shouldSnap);
      const frame: SchemeCanvasFrame = {
        id: createId("frame"),
        x: position.x,
        y: position.y,
        width: FRAME_WIDTH,
        height: FRAME_HEIGHT,
        title: locale === "ru" ? "Фрейм" : "Frame",
        color: "#0f766e",
        fill: "transparent",
        locked: false,
        z_index: nextLayerIndex(layoutRef.current),
      };
      const nextLayout = {
        ...layoutRef.current,
        frames: [...layoutRef.current.frames, frame],
        frame_order: [...normaliseFrameOrder(layoutRef.current.frames, layoutRef.current.frame_order), frame.id],
      };
      setSelectedItem(frame.id);
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout, locale, pushUndoSnapshot, setSelectedItem],
  );

  const addText = useCallback(
    (point: SchemePosition, shouldSnap: boolean) => {
      pushUndoSnapshot();
      const position = positionForNewItem(point, TEXT_WIDTH, TEXT_HEIGHT, layoutRef.current, shouldSnap);
      const text: SchemeTextBlock = {
        id: createId("text"),
        x: position.x,
        y: position.y,
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

  const addComment = useCallback(
    (point: SchemePosition, shouldSnap: boolean) => {
      pushUndoSnapshot();
      const position = shouldSnap ? snapPosition(point, layoutRef.current) : point;
      const comment: SchemeCanvasComment = {
        id: createId("comment"),
        x: position.x,
        y: position.y,
        text: copy.defaultCommentText,
        resolved: false,
      };
      const nextLayout = { ...layoutRef.current, comments: [...layoutRef.current.comments, comment] };
      setSelectedItem(comment.id);
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout, copy.defaultCommentText, pushUndoSnapshot, setSelectedItem],
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
        if (item.kind === "comment") return;
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
      } else if (item.kind === "comment") {
        dragRef.current = { type: "comment", commentId: item.id, start, origin: position };
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
      event.currentTarget.focus({ preventScroll: true });
      const target = event.target as HTMLElement;
      if (target.closest("[data-scheme-board-item='true']")) return;
      event.currentTarget.setPointerCapture?.(event.pointerId);
      const point = pointFromEvent(event);
      const shouldSnap = shouldSnapEvent(event);
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
        addCard(point, shouldSnap);
        return;
      }
      if (tool === "text") {
        setSelectedItem(null);
        addText(point, shouldSnap);
        return;
      }
      if (tool === "rectangle" || tool === "ellipse") {
        setSelectedItem(null);
        addShape(point, tool, shouldSnap);
        return;
      }
      if (tool === "frame") {
        setSelectedItem(null);
        addFrame(point, shouldSnap);
        return;
      }
      if (tool === "comment") {
        setSelectedItem(null);
        addComment(point, shouldSnap);
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
      addComment,
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
      shouldSnapEvent,
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
        const resized = resizedBounds(drag.origin, drag.itemKind, drag.handle, dx, dy);
        const bounds = shouldSnapEvent(event)
          ? snapResizedBounds(drag.origin, drag.itemKind, drag.handle, resized, layoutRef.current)
          : resized;
        setLocalLayout((current) => resizeLayoutItem(current, drag.itemId, drag.itemKind, bounds));
        return;
      }

      const point = pointFromEvent(event);
      const dx = point.x - drag.start.x;
      const dy = point.y - drag.start.y;
      const shouldSnap = shouldSnapEvent(event);
      if (drag.type === "multi") {
        setLocalLayout(() =>
          snapTranslatedSelectedLayout(drag.origin, drag.itemIds, dx, dy, positionedNodes, shouldSnap),
        );
      } else if (drag.type === "node") {
        const position = shouldSnap
          ? snapPosition({ x: drag.origin.x + dx, y: drag.origin.y + dy }, layoutRef.current)
          : { x: drag.origin.x + dx, y: drag.origin.y + dy };
        setLocalLayout((current) => ({
          ...current,
          node_positions: {
            ...current.node_positions,
            [drag.nodeId]: position,
          },
        }));
      } else if (drag.type === "card") {
        const position = shouldSnap
          ? snapPosition({ x: drag.origin.x + dx, y: drag.origin.y + dy }, layoutRef.current)
          : { x: drag.origin.x + dx, y: drag.origin.y + dy };
        setLocalLayout((current) => ({
          ...current,
          cards: current.cards.map((card) =>
            card.id === drag.cardId ? { ...card, x: position.x, y: position.y } : card,
          ),
        }));
      } else if (drag.type === "shape") {
        const position = shouldSnap
          ? snapPosition({ x: drag.origin.x + dx, y: drag.origin.y + dy }, layoutRef.current)
          : { x: drag.origin.x + dx, y: drag.origin.y + dy };
        setLocalLayout((current) => ({
          ...current,
          shapes: current.shapes.map((shape) =>
            shape.id === drag.shapeId
              ? { ...shape, x: position.x, y: position.y }
              : shape,
          ),
        }));
      } else if (drag.type === "frame") {
        const position = shouldSnap
          ? snapPosition({ x: drag.origin.x + dx, y: drag.origin.y + dy }, layoutRef.current)
          : { x: drag.origin.x + dx, y: drag.origin.y + dy };
        setLocalLayout((current) => ({
          ...current,
          frames: current.frames.map((frame) =>
            frame.id === drag.frameId
              ? { ...frame, x: position.x, y: position.y }
              : frame,
          ),
        }));
      } else if (drag.type === "text") {
        const position = shouldSnap
          ? snapPosition({ x: drag.origin.x + dx, y: drag.origin.y + dy }, layoutRef.current)
          : { x: drag.origin.x + dx, y: drag.origin.y + dy };
        setLocalLayout((current) => ({
          ...current,
          texts: current.texts.map((text) =>
            text.id === drag.textId
              ? { ...text, x: position.x, y: position.y }
              : text,
          ),
        }));
      } else if (drag.type === "source") {
        const position = shouldSnap
          ? snapPosition({ x: drag.origin.x + dx, y: drag.origin.y + dy }, layoutRef.current)
          : { x: drag.origin.x + dx, y: drag.origin.y + dy };
        setLocalLayout((current) => ({
          ...current,
          sources: current.sources.map((source) =>
            source.id === drag.sourceId
              ? { ...source, x: position.x, y: position.y }
              : source,
          ),
        }));
      } else if (drag.type === "comment") {
        const position = shouldSnap
          ? snapPosition({ x: drag.origin.x + dx, y: drag.origin.y + dy }, layoutRef.current)
          : { x: drag.origin.x + dx, y: drag.origin.y + dy };
        setLocalLayout((current) => ({
          ...current,
          comments: current.comments.map((comment) =>
            comment.id === drag.commentId ? { ...comment, x: position.x, y: position.y } : comment,
          ),
        }));
      }
    },
    [pointFromEvent, positionedNodes, setLocalLayout, shouldSnapEvent, strokePointFromEvent, updateViewport],
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
      drag.type === "comment" ||
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

  const handleCommentTextChange = useCallback((commentId: string, text: string) => {
    setLocalLayout((current) => ({
      ...current,
      comments: current.comments.map((comment) =>
        comment.id === commentId ? { ...comment, text } : comment,
      ),
    }));
  }, [setLocalLayout]);

  const toggleCommentResolved = useCallback((commentId: string, resolved: boolean) => {
    pushUndoSnapshot();
    const nextLayout = {
      ...layoutRef.current,
      comments: layoutRef.current.comments.map((comment) =>
        comment.id === commentId ? { ...comment, resolved } : comment,
      ),
    };
    setSelectedItem(commentId);
    setLayout(nextLayout);
    layoutRef.current = nextLayout;
    void commitLayout(nextLayout);
  }, [commitLayout, pushUndoSnapshot, setSelectedItem]);

  const commitFacilitation = useCallback(
    (updater: (current: SchemeFacilitationState) => SchemeFacilitationState) => {
      pushUndoSnapshot();
      const nextLayout = {
        ...layoutRef.current,
        facilitation: updater(layoutRef.current.facilitation),
      };
      setLayout(nextLayout);
      layoutRef.current = nextLayout;
      void commitLayout(nextLayout);
    },
    [commitLayout, pushUndoSnapshot],
  );

  const startVotingSession = useCallback(() => {
    const selectedTargets = selectedItems.filter((itemId) => boardItemIds.has(itemId));
    const selectedItemIds = selectedTargets.length > 0 ? selectedTargets : boardItems.map((item) => item.id);
    if (selectedItemIds.length === 0) return;
    commitFacilitation((current) => ({
      ...current,
      voting: {
        ...blankVotingSession(),
        active: true,
        selected_item_ids: selectedItemIds,
      },
    }));
  }, [boardItemIds, boardItems, commitFacilitation, selectedItems]);

  const addVote = useCallback(
    (itemId: string | null) => {
      if (!itemId) return;
      const currentVoting = layoutRef.current.facilitation.voting;
      if (!currentVoting.active) return;
      if (currentVoting.selected_item_ids.length > 0 && !currentVoting.selected_item_ids.includes(itemId)) return;
      commitFacilitation((current) => {
        const existing = current.voting.votes.find((vote) => vote.item_id === itemId);
        const nextCount = current.voting.one_vote_per_object ? 1 : (existing?.count ?? 0) + 1;
        const votes = existing
          ? current.voting.votes.map((vote) =>
              vote.item_id === itemId ? { ...vote, count: nextCount } : vote,
            )
          : [...current.voting.votes, { item_id: itemId, count: nextCount }];
        return {
          ...current,
          voting: {
            ...current.voting,
            votes,
          },
        };
      });
    },
    [commitFacilitation],
  );

  const endVotingSession = useCallback(() => {
    commitFacilitation((current) => ({
      ...current,
      voting: {
        ...current.voting,
        active: false,
      },
    }));
  }, [commitFacilitation]);

  const clearVotingSession = useCallback(() => {
    commitFacilitation((current) => ({
      ...current,
      voting: blankVotingSession(),
    }));
  }, [commitFacilitation]);

  const startTimer = useCallback(() => {
    const startedAtMs = Date.now();
    const remainingSeconds = timerRemainingSeconds(layoutRef.current.facilitation.timer, startedAtMs);
    const nextDurationSeconds = remainingSeconds > 0 ? remainingSeconds : DEFAULT_TIMER_SECONDS;
    commitFacilitation((current) => ({
      ...current,
      timer: {
        active: true,
        duration_seconds: clamp(nextDurationSeconds, MIN_TIMER_SECONDS, MAX_TIMER_SECONDS),
        started_at_ms: startedAtMs,
        paused_remaining_seconds: null,
      },
    }));
    setNowMs(startedAtMs);
  }, [commitFacilitation]);

  const pauseTimer = useCallback(() => {
    const pausedAtMs = Date.now();
    const timer = layoutRef.current.facilitation.timer;
    if (!timer.active) return;
    const pausedRemainingSeconds = timerRemainingSeconds(timer, pausedAtMs);
    commitFacilitation((current) => ({
      ...current,
      timer: {
        ...current.timer,
        active: false,
        started_at_ms: null,
        paused_remaining_seconds: pausedRemainingSeconds,
      },
    }));
    setNowMs(pausedAtMs);
  }, [commitFacilitation]);

  const stopTimer = useCallback(() => {
    commitFacilitation((current) => ({
      ...current,
      timer: blankTimerState(),
    }));
    setNowMs(Date.now());
  }, [commitFacilitation]);

  const addTimerMinute = useCallback(() => {
    commitFacilitation((current) => {
      if (current.timer.active) {
        return {
          ...current,
          timer: {
            ...current.timer,
            duration_seconds: clamp(current.timer.duration_seconds + 60, MIN_TIMER_SECONDS, MAX_TIMER_SECONDS),
          },
        };
      }
      const nextDurationSeconds = clamp(current.timer.duration_seconds + 60, MIN_TIMER_SECONDS, MAX_TIMER_SECONDS);
      const nextPausedRemainingSeconds =
        current.timer.paused_remaining_seconds === null
          ? nextDurationSeconds
          : clamp(current.timer.paused_remaining_seconds + 60, 0, MAX_TIMER_SECONDS);
      return {
        ...current,
        timer: {
          ...current.timer,
          duration_seconds: nextDurationSeconds,
          paused_remaining_seconds: nextPausedRemainingSeconds,
        },
      };
    });
  }, [commitFacilitation]);

  const deleteSelected = useCallback(() => {
    if (selectedItems.length === 0 || !canDeleteSelected) return;
    pushUndoSnapshot();
    const selected = new Set(selectedItems);
    const frames = layoutRef.current.frames.filter((frame) => !selected.has(frame.id));
    const nextLayout = {
      ...layoutRef.current,
      cards: layoutRef.current.cards.filter((card) => !selected.has(card.id)),
      shapes: layoutRef.current.shapes.filter((shape) => !selected.has(shape.id)),
      frames,
      frame_order: normaliseFrameOrder(frames, layoutRef.current.frame_order),
      presentation: normalisePresentation(layoutRef.current.presentation, frames),
      texts: layoutRef.current.texts.filter((text) => !selected.has(text.id)),
      sources: layoutRef.current.sources.filter((source) => !selected.has(source.id)),
      strokes: layoutRef.current.strokes.filter((stroke) => !selected.has(stroke.id)),
      connectors: layoutRef.current.connectors.filter(
        (connector) =>
          !selected.has(connector.id) &&
          (connector.source_id === null || !selected.has(connector.source_id)) &&
          (connector.target_id === null || !selected.has(connector.target_id)),
      ),
      comments: layoutRef.current.comments.filter((comment) => !selected.has(comment.id)),
      facilitation: {
        ...layoutRef.current.facilitation,
        voting: {
          ...layoutRef.current.facilitation.voting,
          selected_item_ids: layoutRef.current.facilitation.voting.selected_item_ids.filter(
            (itemId) => !selected.has(itemId),
          ),
          votes: layoutRef.current.facilitation.voting.votes.filter((vote) => !selected.has(vote.item_id)),
        },
      },
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
        nextLayout.frame_order.push(duplicate.id);
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

  const fitBoard = useCallback(() => {
    const rect = viewportRef.current?.getBoundingClientRect();
    if (!rect || !boardContentBounds) return;
    updateViewport(viewportForBounds(boardContentBounds, rect), true);
  }, [boardContentBounds, updateViewport]);

  const focusOutlineItem = useCallback(
    (item: BoardOutlineItem) => {
      const rect = viewportRef.current?.getBoundingClientRect();
      if (!rect) return;
      setSelectedItem(item.id);
      updateViewport(viewportForFocusedBounds(item.bounds, rect, layoutRef.current.viewport.zoom), true);
    },
    [setSelectedItem, updateViewport],
  );

  const focusOverviewPoint = useCallback(
    (point: SchemePosition) => {
      updateViewport(
        {
          ...layoutRef.current.viewport,
          x: -point.x * layoutRef.current.viewport.zoom,
          y: -point.y * layoutRef.current.viewport.zoom,
        },
        true,
      );
    },
    [updateViewport],
  );

  const focusFromOverviewEvent = useCallback(
    (event: PointerEvent<HTMLButtonElement>) => {
      if (!boardContentBounds) return;
      const rect = event.currentTarget.getBoundingClientRect();
      focusOverviewPoint(overviewPointFromEvent(event.clientX, event.clientY, rect, boardContentBounds));
    },
    [boardContentBounds, focusOverviewPoint],
  );

  const handleOverviewPointerDown = useCallback(
    (event: PointerEvent<HTMLButtonElement>) => {
      if (!boardContentBounds || event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      focusFromOverviewEvent(event);
    },
    [boardContentBounds, focusFromOverviewEvent],
  );

  const handleOverviewPointerMove = useCallback(
    (event: PointerEvent<HTMLButtonElement>) => {
      if (!boardContentBounds || (event.buttons & 1) !== 1) return;
      event.preventDefault();
      event.stopPropagation();
      focusFromOverviewEvent(event);
    },
    [boardContentBounds, focusFromOverviewEvent],
  );

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
  const gridScreenSize = Math.max(4, normaliseGridSize(layout.grid_size) * layout.viewport.zoom);
  const gridStyle = {
    backgroundSize: `${gridScreenSize}px ${gridScreenSize}px`,
    backgroundPosition: `calc(50% + ${layout.viewport.x}px) calc(50% + ${layout.viewport.y}px)`,
  };

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
              <button type="button" disabled={!boardContentBounds} onClick={fitBoard}>
                {copy.fitBoard}
              </button>
              <button
                type="button"
                disabled={orderedFrames.length === 0}
                onClick={isPresenting ? exitPresentation : startPresentation}
              >
                {isPresenting ? copy.exitPresentation : copy.startPresentation}
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
            <label className="scheme-board__snap-toggle">
              <input
                type="checkbox"
                checked={layout.snap_to_grid}
                aria-label={copy.snapToGrid}
                onChange={(event) => updateSnapToGrid(event.target.checked)}
              />
              <span>{copy.snapToGrid}</span>
            </label>
            <label className="scheme-board__grid-size">
              <span>{copy.gridSize}</span>
              <input
                type="number"
                min={MIN_GRID_SIZE}
                max={MAX_GRID_SIZE}
                step={4}
                value={normaliseGridSize(layout.grid_size)}
                aria-label={copy.gridSize}
                onChange={(event) => updateGridSize(Number(event.target.value))}
              />
            </label>
          </div>

          {orderedFrames.length > 0 ? (
            <div className="scheme-board__frames" aria-label={copy.frames}>
              {isPresenting && presentationFrame ? (
                <span className="scheme-board__presentation-status">
                  {copy.presenting(presentationFrameIndex + 1, orderedFrames.length)}
                </span>
              ) : (
                <span>{copy.frames}</span>
              )}
              <button
                type="button"
                className="scheme-board__frame-step"
                aria-label={previousFrameLabel}
                title={previousFrameLabel}
                onClick={() => (isPresenting ? advancePresentation(-1) : focusAdjacentFrame(-1))}
              >
                <span aria-hidden="true">{"<"}</span>
              </button>
              <button
                type="button"
                className="scheme-board__frame-step"
                aria-label={nextFrameLabel}
                title={nextFrameLabel}
                onClick={() => (isPresenting ? advancePresentation(1) : focusAdjacentFrame(1))}
              >
                <span aria-hidden="true">{">"}</span>
              </button>
              {orderedFrames.map((frame, index) => (
                <button
                  key={frame.id}
                  type="button"
                  className={
                    index === activeFrameIndex || frame.id === presentation.frame_id
                      ? "scheme-board__frame-link scheme-board__frame-link--active"
                      : "scheme-board__frame-link"
                  }
                  aria-pressed={index === activeFrameIndex || frame.id === presentation.frame_id}
                  onClick={() => focusFrame(frame)}
                >
                  {frame.title}
                </button>
              ))}
            </div>
          ) : null}

          {selected ? (
            <div className="scheme-board__workspace">
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
              <div className="scheme-board__grid" style={gridStyle} />
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
                {layout.comments.map((comment, index) => (
                  <button
                    key={comment.id}
                    type="button"
                    data-scheme-board-item="true"
                    className={[
                      "scheme-comment-pin",
                      selectedItemSet.has(comment.id) ? "scheme-comment-pin--selected" : "",
                      comment.resolved ? "scheme-comment-pin--resolved" : "",
                    ].filter(Boolean).join(" ")}
                    style={{
                      left: comment.x - COMMENT_PIN_SIZE / 2,
                      top: comment.y - COMMENT_PIN_SIZE / 2,
                      zIndex: 1_000_003,
                    }}
                    aria-label={`Comment ${comment.text}`}
                    onPointerDown={(event) =>
                      handleItemPointerDown(event, { id: comment.id, kind: "comment" }, { x: comment.x, y: comment.y })
                    }
                  >
                    <span>{index + 1}</span>
                  </button>
                ))}
                {voteBadges.map(({ vote, bounds }) => (
                  <span
                    key={vote.item_id}
                    className="scheme-vote-badge"
                    style={{
                      left: bounds.x + Math.max(12, bounds.width) - 14,
                      top: bounds.y - 14,
                      zIndex: 1_000_004,
                    }}
                    aria-label={copy.votes(vote.count)}
                  >
                    {vote.count}
                  </span>
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
              {boardContentBounds ? (
                <button
                  type="button"
                  className="scheme-board__overview"
                  aria-label={copy.overview}
                  onPointerDown={handleOverviewPointerDown}
                  onPointerMove={handleOverviewPointerMove}
                >
                  {boardItems.map((item) => (
                    <span
                      key={item.id}
                      className="scheme-board__overview-item"
                      style={overviewItemStyle(item, boardContentBounds)}
                    />
                  ))}
                  {overviewViewport ? (
                    <span className="scheme-board__overview-viewport" style={overviewViewport} />
                  ) : null}
                </button>
              ) : null}
              </div>
              <aside className="scheme-board__outline" aria-label={copy.outline}>
                <div className="scheme-board__outline-header">
                  <strong>{copy.outline}</strong>
                  <span>{boardOutlineItems.length}</span>
                </div>
                {boardOutlineItems.length > 0 ? (
                  <div className="scheme-board__outline-list">
                    {boardOutlineItems.map((item) => (
                      <button
                        key={`${item.id}-${item.order}`}
                        type="button"
                        className={[
                          "scheme-board__outline-row",
                          selectedItemSet.has(item.id) ? "scheme-board__outline-row--active" : "",
                        ].filter(Boolean).join(" ")}
                        aria-pressed={selectedItemSet.has(item.id)}
                        aria-label={`${copy.outlineKinds[item.kind]} ${item.label}`}
                        onClick={() => focusOutlineItem(item)}
                      >
                        <span>{copy.outlineKinds[item.kind]}</span>
                        <strong>{item.label}</strong>
                        <small>{item.detail}</small>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p>{copy.outlineEmpty}</p>
                )}
                <section className="scheme-board__facilitation" aria-label={copy.facilitation}>
                  <div className="scheme-board__facilitation-header">
                    <strong>{copy.facilitation}</strong>
                  </div>
                  <div className="scheme-board__facilitation-card">
                    <div className="scheme-board__facilitation-card-header">
                      <span>{copy.voting}</span>
                      <strong>{copy.votes(voteTotal)}</strong>
                    </div>
                    <small>{copy.voteScope(voteScopeCount)}</small>
                    <div className="scheme-board__facilitation-actions">
                      {layout.facilitation.voting.active ? (
                        <>
                          <button
                            type="button"
                            disabled={!selectedVoteTargetId}
                            onClick={() => addVote(selectedVoteTargetId)}
                          >
                            {copy.addVote}
                          </button>
                          <button type="button" onClick={endVotingSession}>
                            {copy.endVote}
                          </button>
                        </>
                      ) : (
                        <button type="button" disabled={boardItems.length === 0} onClick={startVotingSession}>
                          {copy.startVote}
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={!layout.facilitation.voting.active && voteTotal === 0}
                        onClick={clearVotingSession}
                      >
                        {copy.clearVote}
                      </button>
                    </div>
                    {layout.facilitation.voting.active && !selectedVoteTargetId ? (
                      <p>{copy.noVoteTarget}</p>
                    ) : null}
                  </div>
                  <div className="scheme-board__facilitation-card">
                    <div className="scheme-board__facilitation-card-header">
                      <span>{copy.timer}</span>
                      <strong className="scheme-board__timer-readout">
                        {formatTimer(remainingTimerSeconds)}
                      </strong>
                    </div>
                    <div className="scheme-board__facilitation-actions">
                      {layout.facilitation.timer.active ? (
                        <button type="button" onClick={pauseTimer}>
                          {copy.pauseTimer}
                        </button>
                      ) : (
                        <button type="button" onClick={startTimer}>
                          {copy.startTimer}
                        </button>
                      )}
                      <button type="button" onClick={stopTimer}>
                        {copy.stopTimer}
                      </button>
                      <button type="button" onClick={addTimerMinute}>
                        {copy.addMinute}
                      </button>
                    </div>
                  </div>
                </section>
                <section className="scheme-board__comments" aria-label={copy.comments}>
                  <div className="scheme-board__comments-header">
                    <strong>{copy.comments}</strong>
                    <span>{copy.unresolvedComments(unresolvedCommentCount)}</span>
                  </div>
                  {layout.comments.length > 0 ? (
                    <div className="scheme-board__comments-list">
                      {layout.comments.map((comment) => (
                        <div
                          key={comment.id}
                          className={[
                            "scheme-board__comment-row",
                            selectedItemSet.has(comment.id) ? "scheme-board__comment-row--active" : "",
                            comment.resolved ? "scheme-board__comment-row--resolved" : "",
                          ].filter(Boolean).join(" ")}
                        >
                          <textarea
                            value={comment.text}
                            aria-label={copy.commentText}
                            onFocus={() => {
                              setSelectedItem(comment.id);
                              beginInlineEdit(comment.id);
                            }}
                            onChange={(event) => handleCommentTextChange(comment.id, event.target.value)}
                            onBlur={finishInlineEdit}
                          />
                          <button
                            type="button"
                            aria-label={comment.resolved ? copy.reopenComment : copy.resolveComment}
                            onClick={() => toggleCommentResolved(comment.id, !comment.resolved)}
                          >
                            {comment.resolved ? copy.reopenComment : copy.resolveComment}
                          </button>
                          {comment.resolved ? <small>{copy.resolvedComment}</small> : null}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>{copy.commentsEmpty}</p>
                  )}
                </section>
              </aside>
            </div>
          ) : (
            <div className="scheme-board__placeholder">{copy.noSelection}</div>
          )}
        </div>
      </div>
    </section>
  );
}
