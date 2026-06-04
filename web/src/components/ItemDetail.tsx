"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteItem,
  downloadItemSummaryAudio,
  getItem,
  reprocessItem,
  startItemSummaryAudio,
} from "@/lib/api";
import { SummaryAudioControls } from "@/components/SummaryAudioControls";
import type { Item, KeyMoment } from "@/lib/types";

interface ItemDetailProps {
  itemId: string;
  onError?: (message: string) => void;
  onDeleted?: (itemId: string) => void | Promise<void>;
  onItemChange?: (item: Item) => void;
  pollIntervalMs?: number;
  showDelete?: boolean;
}

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

/** Detail view for a non-recording Item: summary, key-moments table, key points. */
export function ItemDetail({
  itemId,
  onError,
  onDeleted,
  onItemChange,
  pollIntervalMs = 2000,
  showDelete = true,
}: ItemDetailProps) {
  // Keyed by itemId: resetting to "loading" happens via the deps, and all
  // state writes occur inside the async callbacks (not synchronously in the
  // effect body) to satisfy react-hooks/set-state-in-effect.
  const [state, setState] = useState<{ id: string; item: Item | null; loading: boolean }>({
    id: itemId,
    item: null,
    loading: true,
  });

  const loadItem = useCallback(() => {
    return getItem(itemId)
      .then((value) => {
        setState({ id: itemId, item: value, loading: false });
        onItemChange?.(value);
      })
      .catch((err) => {
        setState({ id: itemId, item: null, loading: false });
        onError?.(err instanceof Error ? err.message : "Couldn't load item.");
      });
  }, [itemId, onError, onItemChange]);

  useEffect(() => {
    void loadItem().catch(() => {
      // Error is surfaced through loadItem's own catch path.
    });
  }, [loadItem]);

  useEffect(() => {
    const audioStatus = state.id === itemId ? state.item?.summary_audio?.status : null;
    if (audioStatus !== "queued" && audioStatus !== "running") return;

    let cancelled = false;
    const interval = window.setInterval(() => {
      void getItem(itemId)
        .then((value) => {
          if (!cancelled) setState({ id: itemId, item: value, loading: false });
        })
        .catch((err) => {
          if (!cancelled) {
            onError?.(err instanceof Error ? err.message : "Couldn't refresh item.");
          }
        });
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [itemId, onError, state.id, state.item?.summary_audio?.status]);

  const [pasteText, setPasteText] = useState("");
  const [recovering, setRecovering] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleReprocess = async (body?: string) => {
    if (recovering) return;
    setRecovering(true);
    try {
      const updated = await reprocessItem(itemId, body ? { body } : {});
      setState({ id: itemId, item: updated, loading: false });
      onItemChange?.(updated);
      setPasteText("");
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Couldn't reprocess this item.");
    } finally {
      setRecovering(false);
    }
  };

  const handleCreateAudio = async () => {
    try {
      const summaryAudio = await startItemSummaryAudio(itemId);
      setState((current) => {
        if (current.id !== itemId || !current.item) return current;
        return {
          ...current,
          item: { ...current.item, summary_audio: summaryAudio },
        };
      });
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Couldn't create summary audio.");
    }
  };

  const handleDownloadAudio = async () => {
    try {
      return await downloadItemSummaryAudio(itemId);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Couldn't download summary audio.");
      throw err;
    }
  };

  const loading = state.loading || state.id !== itemId;
  const item = state.id === itemId ? state.item : null;

  useEffect(() => {
    if (!item || !["fetching", "summarizing"].includes(item.status)) return undefined;
    const id = window.setTimeout(() => void loadItem(), pollIntervalMs);
    return () => window.clearTimeout(id);
  }, [item, loadItem, pollIntervalMs]);

  const handleDelete = async () => {
    if (deleting) return;
    setDeleting(true);
    try {
      await deleteItem(itemId);
      await onDeleted?.(itemId);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Couldn't delete item.");
      setDeleting(false);
    }
  };

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
        <h2 className="item-detail__title">{displayTitle(item.title, item.url)}</h2>
        {showDelete ? (
          <button
            type="button"
            className="ghost-button compact-button"
            disabled={deleting}
            onClick={() => void handleDelete()}
          >
            {deleting ? "Deleting..." : "Delete"}
          </button>
        ) : null}
        {item.url ? (
          <a className="item-detail__source" href={item.url} target="_blank" rel="noreferrer">
            {item.url}
          </a>
        ) : null}
      </header>

      {(item.status === "fetching" || item.status === "summarizing") && !summary?.summary ? (
        <div className="item-detail__processing" data-testid="item-processing">
          {item.status === "fetching"
            ? "Fetching the source text…"
            : "Extracted text is being summarized. This material will update automatically."}
        </div>
      ) : null}

      {(item.status === "needs_input" || item.status === "failed") && !summary?.summary ? (
        <div className="item-detail__recover" data-testid="item-recover">
          <p className="item-detail__notice">
            {item.error?.message ??
              "Couldn't read this automatically — paste the text below, or retry the source."}
          </p>
          <textarea
            className="item-detail__recover-input"
            placeholder="Paste the text here…"
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            data-testid="item-recover-input"
          />
          <div className="item-detail__recover-actions">
            <button
              type="button"
              className="primary-button compact-button"
              disabled={recovering || !pasteText.trim()}
              onClick={() => void handleReprocess(pasteText.trim())}
            >
              {recovering ? "Processing…" : "Process pasted text"}
            </button>
            {item.url ? (
              <button
                type="button"
                className="ghost-button compact-button"
                disabled={recovering}
                onClick={() => void handleReprocess()}
              >
                Retry source
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {summary?.summary ? (
        <section className="item-detail__section">
          <SummaryAudioControls
            state={item.summary_audio}
            onCreate={handleCreateAudio}
            onDownload={handleDownloadAudio}
            filename={`${displayTitle(item.title, item.url).replace(/[/\\]/g, "_")}-summary.mp3`}
          />
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
