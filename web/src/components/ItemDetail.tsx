"use client";

import { useEffect, useState } from "react";
import { getItem } from "@/lib/api";
import type { Item, KeyMoment } from "@/lib/types";

interface ItemDetailProps {
  itemId: string;
  onError?: (message: string) => void;
}

/** Detail view for a non-recording Item: summary, key-moments table, key points. */
export function ItemDetail({ itemId, onError }: ItemDetailProps) {
  // Keyed by itemId: resetting to "loading" happens via the deps, and all
  // state writes occur inside the async callbacks (not synchronously in the
  // effect body) to satisfy react-hooks/set-state-in-effect.
  const [state, setState] = useState<{ id: string; item: Item | null; loading: boolean }>({
    id: itemId,
    item: null,
    loading: true,
  });

  useEffect(() => {
    let cancelled = false;
    getItem(itemId)
      .then((value) => {
        if (!cancelled) setState({ id: itemId, item: value, loading: false });
      })
      .catch((err) => {
        if (!cancelled) {
          setState({ id: itemId, item: null, loading: false });
          onError?.(err instanceof Error ? err.message : "Couldn't load item.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [itemId, onError]);

  const loading = state.loading || state.id !== itemId;
  const item = state.id === itemId ? state.item : null;

  if (loading) {
    return <div className="item-detail item-detail--loading">Loading…</div>;
  }
  if (!item) {
    return <div className="item-detail item-detail--empty">Item not found.</div>;
  }

  const summary = item.summary;
  const keyMoments: KeyMoment[] = summary?.key_moments ?? [];
  const keyPoints = (summary?.key_points ?? []) as string[];

  return (
    <article className="item-detail">
      <header className="item-detail__header">
        <span className="item-detail__kind">{item.kind}</span>
        <h2 className="item-detail__title">{item.title ?? "Untitled"}</h2>
        {item.url ? (
          <a className="item-detail__source" href={item.url} target="_blank" rel="noreferrer">
            {item.url}
          </a>
        ) : null}
      </header>

      {(item.status === "needs_input" || item.status === "failed") && !summary?.summary ? (
        <p className="item-detail__notice">
          {item.error?.message ??
            "Couldn't read this automatically — share the file or paste the text."}
        </p>
      ) : null}

      {summary?.summary ? (
        <section className="item-detail__section">
          <p className="item-detail__summary">{summary.summary}</p>
        </section>
      ) : null}

      {keyMoments.length > 0 ? (
        <section className="item-detail__section">
          <h3 className="item-detail__h3">Key moments</h3>
          <table className="add-anything__moments">
            <thead>
              <tr>
                <th>When</th>
                <th>Moment</th>
                <th>Why it matters</th>
              </tr>
            </thead>
            <tbody>
              {keyMoments.map((moment, index) => (
                <tr key={index}>
                  <td className="add-anything__ts">{moment.timestamp ?? "—"}</td>
                  <td>{moment.moment}</td>
                  <td className="add-anything__why">{moment.why_it_matters}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {keyPoints.length > 0 ? (
        <section className="item-detail__section">
          <h3 className="item-detail__h3">Key points</h3>
          <ul className="item-detail__points">
            {keyPoints.map((point, index) => (
              <li key={index}>{point}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}
