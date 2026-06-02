"use client";

import { useEffect, useRef, useState } from "react";
import { getComparison } from "@/lib/api";
import type { ComparisonSet } from "@/lib/types";

interface ComparisonViewProps {
  comparisonId: string;
  onClose: () => void;
  onError?: (message: string) => void;
}

const TERMINAL = new Set(["ready", "failed"]);

/**
 * Renders one comparison set as a modal: polls until the background table build
 * finishes, then shows the induced columns (Item × attributes). No fallback — a
 * failed build surfaces its reason rather than a blank table.
 */
export function ComparisonView({ comparisonId, onClose, onError }: ComparisonViewProps) {
  const [set, setSet] = useState<ComparisonSet | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const cs = await getComparison(comparisonId);
        if (cancelled) return;
        setSet(cs);
        if (!TERMINAL.has(cs.status)) {
          timer = window.setTimeout(tick, 2000);
        }
      } catch (err) {
        if (cancelled) return;
        const message =
          err instanceof Error ? err.message : "Couldn't load the comparison.";
        setLoadError(message);
        onErrorRef.current?.(message);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [comparisonId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const columns = set?.columns ?? [];
  const rows = set?.rows ?? [];

  return (
    <div
      className="comparison-view__backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Comparison"
      onClick={onClose}
    >
      <div
        className="comparison-view"
        onClick={(e) => e.stopPropagation()}
        data-testid="comparison-view"
      >
        <header className="comparison-view__header">
          <h2 className="comparison-view__title">{set?.title ?? "Comparison"}</h2>
          <button
            type="button"
            className="ghost-button compact-button"
            onClick={onClose}
            aria-label="Close comparison"
          >
            Close
          </button>
        </header>

        <div className="comparison-view__body">
          {loadError ? (
            <p className="comparison-view__error">{loadError}</p>
          ) : !set ? (
            <p className="comparison-view__status">Loading…</p>
          ) : set.status === "failed" ? (
            <p className="comparison-view__error">
              {set.schema_rationale ?? "Couldn't build this comparison."}
            </p>
          ) : set.status !== "ready" ? (
            <p className="comparison-view__status">Building comparison…</p>
          ) : columns.length === 0 ? (
            <p className="comparison-view__status">
              No comparable attributes were found across these items.
            </p>
          ) : (
            <>
              <table className="comparison-view__table">
                <thead>
                  <tr>
                    <th>Item</th>
                    {columns.map((col) => (
                      <th key={col.name}>{col.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.item_id}>
                      <th scope="row">{row.title}</th>
                      {columns.map((col) => {
                        const value = row.values?.[col.name];
                        const blank =
                          value === null || value === undefined || value === "";
                        return (
                          <td key={col.name} className={blank ? "comparison-view__cell--blank" : ""}>
                            {blank ? "—" : String(value)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              {set.schema_rationale ? (
                <p className="comparison-view__rationale">{set.schema_rationale}</p>
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
