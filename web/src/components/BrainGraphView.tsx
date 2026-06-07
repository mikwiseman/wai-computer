"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { BrainGraph } from "@/lib/types";

// react-force-graph-2d touches window/canvas, so it must load client-only.
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const KIND_COLOR: Record<string, string> = {
  person: "#e0823d",
  topic: "#4a90d9",
  project: "#3da35d",
  item: "#9aa0a6",
  recording: "#a06bd4",
  chat: "#c47a35",
};

const ENTITY_KINDS = new Set(["person", "topic", "project"]);
const SOURCE_KINDS = new Set(["item", "recording", "chat"]);

export interface ForceGraphNode {
  id: string;
  label: string;
  kind: string;
  degree: number;
  val: number;
  color: string;
  showLabel: boolean;
  x?: number;
  y?: number;
}

export interface ForceGraphLink {
  source: string;
  target: string;
  type: string;
  weight: number;
}

/** Pure: map the API graph into react-force-graph's {nodes, links}, optionally
 *  dropping item/recording/chat source nodes (and any edges that referenced them). */
export function buildForceGraph(
  graph: BrainGraph,
  showSources: boolean,
): { nodes: ForceGraphNode[]; links: ForceGraphLink[] } {
  const keep = (kind: string) => showSources || !SOURCE_KINDS.has(kind);
  const visibleNodes = graph.nodes.filter((n) => keep(n.kind));
  const labeledIds = new Set(
    [...visibleNodes]
      .filter((n) => ENTITY_KINDS.has(n.kind))
      .sort((a, b) => b.degree - a.degree || a.label.localeCompare(b.label))
      .slice(0, 24)
      .map((n) => n.id),
  );
  const nodes: ForceGraphNode[] = visibleNodes.map((n) => ({
    id: n.id,
    label: n.label,
    kind: n.kind,
    degree: n.degree,
    val: 1 + Math.log2(n.degree + 1),
    color: KIND_COLOR[n.kind] ?? KIND_COLOR.item,
    showLabel: labeledIds.has(n.id),
  }));
  const present = new Set(nodes.map((n) => n.id));
  const links: ForceGraphLink[] = graph.edges
    .filter((e) => present.has(e.source) && present.has(e.target))
    .map((e) => ({ source: e.source, target: e.target, type: e.type, weight: e.weight }));
  return { nodes, links };
}

export function sourceRefFromGraphNode(
  node: { id?: string | number; kind?: string },
): { sourceKind: "item" | "recording" | "chat"; sourceId: string } | null {
  if (!node || typeof node.id !== "string" || !node.kind || !SOURCE_KINDS.has(node.kind)) {
    return null;
  }
  const prefix = `${node.kind}:`;
  return {
    sourceKind: node.kind as "item" | "recording" | "chat",
    sourceId: node.id.startsWith(prefix) ? node.id.slice(prefix.length) : node.id,
  };
}

interface BrainGraphViewProps {
  graph: BrainGraph;
  showSources: boolean;
  onToggleSources: (value: boolean) => void;
  onFocusEntity: (entityId: string) => void;
  onOpenSource?: (sourceKind: "recording" | "item" | "chat", sourceId: string) => void;
  focused: boolean;
  onResetFocus: () => void;
  locale?: string;
}

export function BrainGraphView({
  graph,
  showSources,
  onToggleSources,
  onFocusEntity,
  onOpenSource,
  focused,
  onResetFocus,
  locale = "en",
}: BrainGraphViewProps) {
  const t = (en: string, ru: string) => (locale === "ru" ? ru : en);
  const data = useMemo(() => buildForceGraph(graph, showSources), [graph, showSources]);

  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 600, height: 520 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;
    const measure = () =>
      setSize({ width: el.clientWidth || 600, height: Math.max(360, el.clientHeight || 520) });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const handleNodeClick = useCallback(
    (node: { id?: string | number; kind?: string }) => {
      if (node && typeof node.id === "string" && node.kind && ENTITY_KINDS.has(node.kind)) {
        onFocusEntity(node.id);
        return;
      }
      const source = sourceRefFromGraphNode(node);
      if (source) onOpenSource?.(source.sourceKind, source.sourceId);
    },
    [onFocusEntity, onOpenSource],
  );

  const paintNodeLabel = useCallback(
    (node: ForceGraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (!node.showLabel || typeof node.x !== "number" || typeof node.y !== "number") return;
      const fontSize = Math.max(9, Math.min(13, 11 / globalScale));
      const radius = 4 * (node.val || 1);
      ctx.font = `${fontSize}px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
      const textWidth = ctx.measureText(node.label).width;
      const x = node.x - textWidth / 2;
      const y = node.y + radius + fontSize + 3;
      ctx.fillStyle = "rgba(30, 32, 28, 0.78)";
      ctx.fillRect(x - 4, y - fontSize + 1, textWidth + 8, fontSize + 5);
      ctx.fillStyle = "rgba(244, 242, 234, 0.95)";
      ctx.fillText(node.label, x, y);
    },
    [],
  );

  return (
    <div className="brain-graph">
      <div className="brain-graph__toolbar">
        <span className="brain-graph__count">
          {data.nodes.length} {t("nodes", "узлов")} · {data.links.length} {t("links", "связей")}
        </span>
        <label className="brain-graph__toggle">
          <input
            type="checkbox"
            checked={showSources}
            onChange={(e) => onToggleSources(e.target.checked)}
          />
          {t("Show sources", "Показать источники")}
        </label>
        {focused ? (
          <button type="button" className="brain-graph__reset" onClick={onResetFocus}>
            {t("Reset view", "Сбросить вид")}
          </button>
        ) : null}
      </div>
      <div ref={containerRef} className="brain-graph__canvas">
        <ForceGraph2D
          graphData={data}
          width={size.width}
          height={size.height}
          nodeLabel="label"
          nodeColor={(node) => node.color}
          nodeVal={(node) => node.val}
          nodeRelSize={4}
          nodeCanvasObjectMode={() => "after"}
          nodeCanvasObject={(node, ctx, globalScale) =>
            paintNodeLabel(node as ForceGraphNode, ctx, globalScale)
          }
          linkColor={() => "rgba(140,140,150,0.28)"}
          linkWidth={(link) => Math.min(3, 0.5 + (link.weight ?? 1) * 0.5)}
          onNodeClick={handleNodeClick}
          cooldownTicks={120}
        />
      </div>
    </div>
  );
}
