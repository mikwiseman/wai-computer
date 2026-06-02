"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createComparison, deleteItem, listItems } from "@/lib/api";
import type { ItemListEntry } from "@/lib/types";
import { ItemDetail } from "@/components/ItemDetail";
import { ComparisonView } from "@/components/ComparisonView";

interface ItemsFeedProps {
  onError?: (message: string) => void;
  /** Bump to force a reload (e.g. after "Add anything" creates an item). */
  reloadKey?: number;
}

const KIND_FILTERS = [
  { key: "", label: "All" },
  { key: "article", label: "Articles" },
  { key: "video", label: "Videos" },
  { key: "pdf", label: "PDFs" },
  { key: "note", label: "Notes" },
  { key: "document", label: "Docs" },
  { key: "presentation", label: "Slides" },
  { key: "spreadsheet", label: "Sheets" },
  { key: "mcp_resource", label: "Connected" },
] as const;

// status -> badge. "ready" has no badge (the calm default). needs_input/failed
// carry the error message in a tooltip so a stuck item is never silent.
const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  fetching: { label: "fetching…", cls: "items-feed__badge--pending" },
  summarizing: { label: "summarizing…", cls: "items-feed__badge--pending" },
  needs_input: { label: "needs input", cls: "items-feed__badge--attention" },
  failed: { label: "failed", cls: "items-feed__badge--error" },
};

function displayTitle(title: string | null, url: string | null): string {
  const cleaned = title?.trim();
  if (
    cleaned &&
    !["untitled", "[untitled]", "без названия", "[без названия]"].includes(
      cleaned.toLowerCase(),
    )
  ) {
    return cleaned;
  }
  return url ?? "Untitled";
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

/**
 * The non-recording half of the unified feed: everything captured or ingested
 * (articles, links, notes, MCP-pulled resources), filterable by kind, with a
 * drill-in to the item's summary + key-moments table.
 */
export function ItemsFeed({ onError, reloadKey = 0 }: ItemsFeedProps) {
  const [entries, setEntries] = useState<ItemListEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [kind, setKind] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Multi-select → compare (mirrors the Mac Content feed's compare flow).
  const [compareSelection, setCompareSelection] = useState<Set<string>>(new Set());
  const [activeComparisonId, setActiveComparisonId] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await listItems(kind ? { kind } : undefined);
      setEntries(response.items);
      setTotal(response.total);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Couldn't load items.");
    } finally {
      setLoading(false);
    }
    // reloadKey is an intentional dependency: bumping it forces a refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, onError, reloadKey]);

  useEffect(() => {
    void load();
  }, [load]);

  // Refresh when the tab/window regains focus so stale "summarizing…" badges
  // and needs_input notices resolve without a manual reload.
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState !== "hidden") void load();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [load]);

  // While any item is still processing, poll so its badge resolves on its own.
  const hasPending = useMemo(
    () => entries.some((e) => e.status === "fetching" || e.status === "summarizing"),
    [entries],
  );
  useEffect(() => {
    if (!hasPending) return undefined;
    const id = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(id);
  }, [hasPending, load]);

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteItem(id);
        if (selectedId === id) setSelectedId(null);
        await load();
      } catch (err) {
        onError?.(err instanceof Error ? err.message : "Couldn't delete item.");
      }
    },
    [load, onError, selectedId],
  );

  const selected = useMemo(
    () => entries.find((entry) => entry.id === selectedId) ?? null,
    [entries, selectedId],
  );

  const toggleCompare = useCallback((id: string) => {
    setCompareSelection((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleCompare = useCallback(async () => {
    if (compareSelection.size < 2 || building) return;
    setBuilding(true);
    try {
      const cs = await createComparison({ item_ids: [...compareSelection] });
      setActiveComparisonId(cs.id);
      setCompareSelection(new Set());
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Couldn't start the comparison.");
    } finally {
      setBuilding(false);
    }
  }, [compareSelection, building, onError]);

  return (
    <div className="items-feed">
      <div className="items-feed__filters" role="tablist" aria-label="Filter by kind">
        {KIND_FILTERS.map((filter) => (
          <button
            key={filter.key || "all"}
            type="button"
            role="tab"
            aria-selected={kind === filter.key}
            className={`items-feed__chip ${kind === filter.key ? "items-feed__chip--active" : ""}`}
            onClick={() => {
              setKind(filter.key);
              setSelectedId(null);
              setCompareSelection(new Set());
            }}
          >
            {filter.label}
          </button>
        ))}
      </div>

      <div className="items-feed__layout">
        <section className="items-feed__list" aria-label="Items">
          <header className="items-feed__list-header">
            <span>{total} item{total === 1 ? "" : "s"}</span>
            {compareSelection.size >= 2 ? (
              <button
                type="button"
                className="ghost-button compact-button"
                onClick={() => void handleCompare()}
                disabled={building}
              >
                {building ? "Comparing…" : `Compare ${compareSelection.size}`}
              </button>
            ) : null}
          </header>
          {loading ? (
            <p className="items-feed__status">Loading…</p>
          ) : entries.length === 0 ? (
            <p className="items-feed__empty">
              Nothing here yet. Use “Add anything” or connect a source.
            </p>
          ) : (
            <ul className="items-feed__rows">
              {entries.map((entry) => (
                <li key={entry.id} className="items-feed__row-wrap">
                  <input
                    type="checkbox"
                    className="items-feed__check"
                    aria-label={`Select ${displayTitle(entry.title, entry.url)} to compare`}
                    checked={compareSelection.has(entry.id)}
                    onChange={() => toggleCompare(entry.id)}
                  />
                  <button
                    type="button"
                    className={`items-feed__row ${
                      selectedId === entry.id ? "items-feed__row--active" : ""
                    }`}
                    aria-current={selectedId === entry.id ? "true" : undefined}
                    onClick={() => setSelectedId(entry.id)}
                  >
                    <span className="items-feed__row-title">
                      {displayTitle(entry.title, entry.url)}
                    </span>
                    <span className="items-feed__row-meta">
                      <span className="items-feed__badge">{entry.kind}</span>
                      {STATUS_BADGE[entry.status] ? (
                        <span
                          className={`items-feed__badge ${STATUS_BADGE[entry.status].cls}`}
                          title={entry.error?.message ?? undefined}
                        >
                          {STATUS_BADGE[entry.status].label}
                        </span>
                      ) : null}
                      <span className="items-feed__time">{relativeTime(entry.created_at)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="items-feed__detail" aria-label="Item detail">
          {selected ? (
            <>
              <div className="items-feed__detail-actions">
                <button
                  type="button"
                  className="ghost-button compact-button"
                  onClick={() => void handleDelete(selected.id)}
                >
                  Delete
                </button>
              </div>
              <ItemDetail itemId={selected.id} onError={onError} />
            </>
          ) : (
            <p className="items-feed__placeholder">Select an item to see its summary.</p>
          )}
        </section>
      </div>

      {activeComparisonId ? (
        <ComparisonView
          comparisonId={activeComparisonId}
          onClose={() => setActiveComparisonId(null)}
          onError={onError}
        />
      ) : null}
    </div>
  );
}
