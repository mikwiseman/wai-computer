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
import { SummaryMarkdown } from "@/components/SummaryMarkdown";
import type { Item, KeyMoment } from "@/lib/types";

type Locale = "en" | "ru";

interface Copy {
  untitled: string;
  loading: string;
  notFound: string;
  deleting: string;
  delete: string;
  deleteConfirmTitle: string;
  deleteConfirmBody: string;
  cancel: string;
  fetching: string;
  summarizing: string;
  sourceText: string;
  recoverNotice: string;
  pastePlaceholder: string;
  processing: string;
  processPasted: string;
  retrySource: string;
  keyMoments: string;
  when: string;
  moment: string;
  whyItMatters: string;
  keyPoints: string;
  errLoad: string;
  errRefresh: string;
  errReprocess: string;
  errCreateAudio: string;
  errDownloadAudio: string;
  errDelete: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    untitled: "Untitled",
    loading: "Loading…",
    notFound: "Item not found.",
    deleting: "Deleting…",
    delete: "Delete",
    deleteConfirmTitle: "Delete this material?",
    deleteConfirmBody: "It will be removed permanently — this can't be undone.",
    cancel: "Cancel",
    fetching: "Fetching the source text…",
    summarizing: "Extracted text is being summarized. This material will update automatically.",
    sourceText: "Source text",
    recoverNotice: "Couldn't read this automatically — paste the text below, or retry the source.",
    pastePlaceholder: "Paste the text here…",
    processing: "Processing…",
    processPasted: "Process pasted text",
    retrySource: "Retry source",
    keyMoments: "Key moments",
    when: "When",
    moment: "Moment",
    whyItMatters: "Why it matters",
    keyPoints: "Key points",
    errLoad: "Couldn't load item.",
    errRefresh: "Couldn't refresh item.",
    errReprocess: "Couldn't reprocess this item.",
    errCreateAudio: "Couldn't create summary audio.",
    errDownloadAudio: "Couldn't download summary audio.",
    errDelete: "Couldn't delete item.",
  },
  ru: {
    untitled: "Без названия",
    loading: "Загрузка…",
    notFound: "Материал не найден.",
    deleting: "Удаление…",
    delete: "Удалить",
    deleteConfirmTitle: "Удалить этот материал?",
    deleteConfirmBody: "Он будет удалён навсегда — это нельзя отменить.",
    cancel: "Отмена",
    fetching: "Загружаем исходный текст…",
    summarizing: "Извлечённый текст обрабатывается. Материал обновится автоматически.",
    sourceText: "Исходный текст",
    recoverNotice: "Не удалось прочитать автоматически — вставьте текст ниже или повторите загрузку источника.",
    pastePlaceholder: "Вставьте текст сюда…",
    processing: "Обработка…",
    processPasted: "Обработать вставленный текст",
    retrySource: "Повторить источник",
    keyMoments: "Ключевые моменты",
    when: "Когда",
    moment: "Момент",
    whyItMatters: "Почему это важно",
    keyPoints: "Ключевые тезисы",
    errLoad: "Не удалось загрузить материал.",
    errRefresh: "Не удалось обновить материал.",
    errReprocess: "Не удалось переобработать материал.",
    errCreateAudio: "Не удалось создать аудио-резюме.",
    errDownloadAudio: "Не удалось скачать аудио-резюме.",
    errDelete: "Не удалось удалить материал.",
  },
};

interface ItemDetailProps {
  itemId: string;
  onError?: (message: string) => void;
  onDeleted?: (itemId: string) => void | Promise<void>;
  onItemChange?: (item: Item) => void;
  pollIntervalMs?: number;
  showDelete?: boolean;
  locale?: Locale;
}

function displayTitle(
  title: string | null,
  url: string | null,
  body: string | null,
  untitled: string,
): string {
  const cleaned = title?.trim();
  if (
    cleaned &&
    !["untitled", "[untitled]", "без названия", "[без названия]"].includes(
      cleaned.toLowerCase(),
    )
  ) {
    return cleaned;
  }
  if (url) return url;
  const excerpt = body?.trim().replace(/\s+/g, " ");
  if (excerpt) {
    return excerpt.length > 64 ? `${excerpt.slice(0, 63).trimEnd()}…` : excerpt;
  }
  return untitled;
}

/** Detail view for a non-recording Item: summary, key-moments table, key points. */
export function ItemDetail({
  itemId,
  onError,
  onDeleted,
  onItemChange,
  pollIntervalMs = 2000,
  showDelete = true,
  locale = "en",
}: ItemDetailProps) {
  const copy = COPY[locale];
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
        onError?.(err instanceof Error ? err.message : copy.errLoad);
      });
  }, [itemId, onError, onItemChange, copy.errLoad]);

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
            onError?.(err instanceof Error ? err.message : copy.errRefresh);
          }
        });
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [itemId, onError, state.id, state.item?.summary_audio?.status, copy.errRefresh]);

  const [pasteText, setPasteText] = useState("");
  const [recovering, setRecovering] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const handleReprocess = async (body?: string) => {
    if (recovering) return;
    setRecovering(true);
    try {
      const updated = await reprocessItem(itemId, body ? { body } : {});
      setState({ id: itemId, item: updated, loading: false });
      onItemChange?.(updated);
      setPasteText("");
    } catch (err) {
      onError?.(err instanceof Error ? err.message : copy.errReprocess);
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
      onError?.(err instanceof Error ? err.message : copy.errCreateAudio);
    }
  };

  const handleDownloadAudio = async () => {
    try {
      return await downloadItemSummaryAudio(itemId);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : copy.errDownloadAudio);
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
      onError?.(err instanceof Error ? err.message : copy.errDelete);
      setDeleting(false);
    }
  };

  if (loading) {
    return <div className="item-detail item-detail--loading">{copy.loading}</div>;
  }
  if (!item) {
    return <div className="item-detail item-detail--empty">{copy.notFound}</div>;
  }

  const summary = item.summary;
  const keyMoments: KeyMoment[] = summary?.key_moments ?? [];
  const keyPoints = (summary?.key_points ?? []) as string[];

  return (
    <article className="item-detail">
      <header className="item-detail__header">
        <span className="item-detail__kind">{item.kind}</span>
        <h2 className="item-detail__title">
          {displayTitle(item.title, item.url, item.body, copy.untitled)}
        </h2>
        {showDelete ? (
          <button
            type="button"
            className="ghost-button compact-button"
            data-testid="item-delete"
            disabled={deleting}
            onClick={() => setConfirmingDelete(true)}
          >
            {deleting ? copy.deleting : copy.delete}
          </button>
        ) : null}
        {item.url ? (
          <a className="item-detail__source" href={item.url} target="_blank" rel="noreferrer">
            {item.url}
          </a>
        ) : null}
      </header>

      {(item.status === "fetching" || item.status === "summarizing") && !summary?.summary ? (
        <div className="item-detail__processing" data-testid="item-processing" role="status">
          {item.status === "fetching" ? copy.fetching : copy.summarizing}
        </div>
      ) : null}

      {(item.status === "needs_input" || item.status === "failed") && !summary?.summary ? (
        <div className="item-detail__recover" data-testid="item-recover">
          <p className="item-detail__notice">
            {item.error?.message ?? copy.recoverNotice}
          </p>
          <textarea
            className="item-detail__recover-input"
            placeholder={copy.pastePlaceholder}
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
              {recovering ? copy.processing : copy.processPasted}
            </button>
            {item.url ? (
              <button
                type="button"
                className="ghost-button compact-button"
                disabled={recovering}
                onClick={() => void handleReprocess()}
              >
                {copy.retrySource}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {summary?.summary ? (
        <section className="item-detail__section">
          <SummaryAudioControls
            locale={locale}
            state={item.summary_audio}
            onCreate={handleCreateAudio}
            onDownload={handleDownloadAudio}
            filename={`${displayTitle(item.title, item.url, item.body, copy.untitled).replace(/[/\\]/g, "_")}-summary.mp3`}
          />
          <div className="item-detail__summary">
            <SummaryMarkdown text={summary.summary} />
          </div>
        </section>
      ) : null}

      {keyMoments.length > 0 ? (
        <section className="item-detail__section">
          <h3 className="item-detail__h3">{copy.keyMoments}</h3>
          <table className="add-anything__moments">
            <thead>
              <tr>
                <th>{copy.when}</th>
                <th>{copy.moment}</th>
                <th>{copy.whyItMatters}</th>
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
          <h3 className="item-detail__h3">{copy.keyPoints}</h3>
          <ul className="item-detail__points">
            {keyPoints.map((point, index) => (
              <li key={index}>{point}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {item.body?.trim() ? (
        summary?.summary ? (
          <details className="item-detail__section item-detail__source-text" data-testid="item-body">
            <summary className="item-detail__h3 item-detail__source-toggle">
              {copy.sourceText}
            </summary>
            <p className="item-detail__body">{item.body}</p>
          </details>
        ) : (
          <section className="item-detail__section item-detail__source-text" data-testid="item-body">
            <h3 className="item-detail__h3">{copy.sourceText}</h3>
            <p className="item-detail__body">{item.body}</p>
          </section>
        )
      ) : null}
      {confirmingDelete ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          data-testid="item-delete-modal"
        >
          <div className="modal-card">
            <h3>{copy.deleteConfirmTitle}</h3>
            <p className="settings-note">{copy.deleteConfirmBody}</p>
            <div className="row-actions">
              <button
                type="button"
                className="ghost-button compact-button"
                data-testid="item-delete-cancel"
                onClick={() => setConfirmingDelete(false)}
              >
                {copy.cancel}
              </button>
              <button
                type="button"
                className="ghost-button compact-button danger-button"
                data-testid="item-delete-confirm"
                disabled={deleting}
                onClick={() => {
                  setConfirmingDelete(false);
                  void handleDelete();
                }}
              >
                {copy.delete}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </article>
  );
}
