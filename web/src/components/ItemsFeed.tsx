"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { deleteItem, listItems } from "@/lib/api";
import type { ItemListEntry } from "@/lib/types";
import { ItemDetail } from "@/components/ItemDetail";

interface ItemsFeedProps {
  onError?: (message: string) => void;
}

const KIND_FILTERS = [
  { key: "", label: "All" },
  { key: "article", label: "Articles" },
  { key: "video", label: "Videos" },
  { key: "note", label: "Notes" },
  { key: "mcp_resource", label: "Connected" },
] as const;

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
export function ItemsFeed({ onError }: ItemsFeedProps) {
  const [entries, setEntries] = useState<ItemListEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [kind, setKind] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

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
  }, [kind, onError]);

  useEffect(() => {
    void load();
  }, [load]);

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
                <li key={entry.id}>
                  <button
                    type="button"
                    className={`items-feed__row ${
                      selectedId === entry.id ? "items-feed__row--active" : ""
                    }`}
                    aria-current={selectedId === entry.id ? "true" : undefined}
                    onClick={() => setSelectedId(entry.id)}
                  >
                    <span className="items-feed__row-title">
                      {entry.title ?? entry.url ?? "Untitled"}
                    </span>
                    <span className="items-feed__row-meta">
                      <span className="items-feed__badge">{entry.kind}</span>
                      {entry.has_summary ? null : (
                        <span className="items-feed__badge items-feed__badge--pending">
                          summarizing…
                        </span>
                      )}
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
    </div>
  );
}
