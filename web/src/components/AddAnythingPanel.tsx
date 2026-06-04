"use client";

import { useCallback, useRef, useState } from "react";
import { createItem, getItem, uploadItem } from "@/lib/api";
import type { Item, KeyMoment } from "@/lib/types";

interface AddAnythingPanelProps {
  onCreated?: (item: Item) => void;
  onRecordingQueued?: (recordingId: string) => void;
  onError?: (message: string) => void;
  locale?: "en" | "ru";
  captureMode?: "inbox" | "summary";
  folderId?: string | null;
}

const URL_RE = /^https?:\/\/\S+$/i;
const POLL_INTERVAL_MS = 2000;
const POLL_MAX_ATTEMPTS = 30; // ~60s for the background summary to land

/**
 * "Add anything" capture — paste a URL or text, it lands in the brain and
 * (for content with a body) shows the summary + key-moments table once the
 * background job finishes. The web counterpart to the Telegram forward flow.
 */
export function AddAnythingPanel({
  onCreated,
  onRecordingQueued,
  onError,
  locale = "en",
  captureMode = "summary",
  folderId = null,
}: AddAnythingPanelProps) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [result, setResult] = useState<Item | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const busyRef = useRef(false);

  const pollForSummary = useCallback(async (itemId: string) => {
    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt += 1) {
      const item = await getItem(itemId);
      if (item.summary && item.summary.summary) {
        return item;
      }
      if (item.state === "needs_input") {
        return item; // e.g. Instagram "share the file"
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
    return getItem(itemId);
  }, []);

  const handleSubmit = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setResult(null);
    const isUrl = URL_RE.test(trimmed);
    setStatus(
      captureMode === "inbox"
        ? locale === "ru"
          ? "Сохраняем в Инбокс..."
          : "Saving to Inbox..."
        : isUrl
          ? locale === "ru"
            ? "Загружаем и резюмируем..."
            : "Fetching and summarizing..."
          : locale === "ru"
            ? "Резюмируем..."
            : "Summarizing...",
    );
    try {
      const folderInput = folderId ? { folder_id: folderId } : {};
      const created = isUrl
        ? await createItem({
            source: "url",
            kind: "article",
            url: trimmed,
            ...folderInput,
          })
        : await createItem({
            source: "paste",
            kind: "note",
            body: trimmed,
            ...folderInput,
          });
      onCreated?.(created);
      if (captureMode === "inbox") {
        setValue("");
        setStatus(locale === "ru" ? "Сохранено в Инбокс." : "Saved to Inbox.");
        return;
      }
      const finished = await pollForSummary(created.id);
      setResult(finished);
      setValue("");
      setStatus("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't add that.";
      setStatus("");
      onError?.(message);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [captureMode, folderId, locale, value, onCreated, onError, pollForSummary]);

  const handleFile = useCallback(
    async (file: File) => {
      if (busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setResult(null);
      setStatus(locale === "ru" ? `Загружаем ${file.name}...` : `Uploading ${file.name}...`);
      try {
        const outcome = folderId
          ? await uploadItem(file, { folderId })
          : await uploadItem(file);
        if (outcome.kind === "recording") {
          setStatus(
            locale === "ru"
              ? "Расшифровываем — запись уже в Инбоксе."
              : "Transcribing — the recording is now in your Inbox.",
          );
          onRecordingQueued?.(outcome.recording_id);
          return;
        }
        const created = outcome.item;
        onCreated?.(created);
        if (captureMode === "inbox") {
          setStatus(locale === "ru" ? "Файл сохранён в Инбокс." : "File saved to Inbox.");
          return;
        }
        setStatus(locale === "ru" ? "Резюмируем..." : "Summarizing...");
        const finished = await pollForSummary(created.id);
        setResult(finished);
        setStatus("");
      } catch (err) {
        setStatus("");
        onError?.(err instanceof Error ? err.message : "Couldn't upload that file.");
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [captureMode, folderId, locale, onCreated, onRecordingQueued, onError, pollForSummary],
  );

  const keyMoments: KeyMoment[] = result?.summary?.key_moments ?? [];
  const fetchError =
    result &&
    (result.state === "needs_input" || result.status === "failed") &&
    !result.summary?.summary
      ? result.error?.message ??
        "Couldn't read that link automatically — share the file or paste the text."
      : null;

  return (
    <div
      className={`add-anything${dragOver ? " add-anything--dragover" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!dragOver) setDragOver(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        setDragOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const file = e.dataTransfer.files?.[0];
        if (file) void handleFile(file);
      }}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.txt,.md,.mp3,.wav,.m4a,.aac,.ogg,.opus,.flac,.mp4,.mov,.mkv,.webm,application/pdf,text/plain,text/markdown,audio/*,video/*"
        style={{ display: "none" }}
        data-testid="add-anything-file"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleFile(file);
          e.target.value = "";
        }}
      />
      <div className="add-anything__input-row">
        <textarea
          className="add-anything__input"
          placeholder={
            locale === "ru"
              ? "Вставьте ссылку или текст..."
              : "Paste a link or any text..."
          }
          value={value}
          rows={3}
          disabled={busy}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void handleSubmit();
            }
          }}
        />
        <div className="add-anything__actions">
          <button
            type="button"
            className="wai-primary-button add-anything__submit"
            disabled={busy || !value.trim()}
            onClick={() => void handleSubmit()}
          >
            {busy
              ? locale === "ru"
                ? "Добавляем..."
                : "Adding..."
              : captureMode === "summary"
                ? locale === "ru"
                  ? "Добавить в мозг"
                  : "Add to brain"
              : locale === "ru"
                ? "Добавить"
                : "Add"}
          </button>
          <button
            type="button"
            className="add-anything__attach"
            disabled={busy}
            onClick={() => fileInputRef.current?.click()}
          >
            {locale === "ru" ? "Прикрепить файл" : "Attach file"}
          </button>
        </div>
      </div>
      <p className="add-anything__hint">
        {locale === "ru"
          ? "Перетащите документ, аудио или видео сюда, или вставьте ссылку выше."
          : "Drop a document, audio, or video file here, or paste a link above."}
      </p>

      {status ? (
        <p className="add-anything__status" role="status" aria-live="polite">
          {status}
        </p>
      ) : null}
      {fetchError ? (
        <p className="add-anything__error" role="alert">
          {fetchError}
        </p>
      ) : null}

      {result?.summary?.summary ? (
        <div className="add-anything__result">
          {result.title ? <h3 className="add-anything__title">{result.title}</h3> : null}
          <p className="add-anything__summary">{result.summary.summary}</p>

          {keyMoments.length > 0 ? (
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
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
