"use client";

import { useCallback, useRef, useState } from "react";
import { createItem, getItem, uploadItem } from "@/lib/api";
import type { Item, KeyMoment } from "@/lib/types";

interface AddAnythingPanelProps {
  onCreated?: (item: Item) => void;
  onError?: (message: string) => void;
}

const URL_RE = /^https?:\/\/\S+$/i;
const POLL_INTERVAL_MS = 2000;
const POLL_MAX_ATTEMPTS = 30; // ~60s for the background summary to land
const ACCEPTED_FILE_TYPES = [
  ".pdf",
  ".txt",
  ".md",
  ".markdown",
  ".html",
  ".htm",
  ".doc",
  ".docx",
  ".rtf",
  ".csv",
  ".json",
  ".pptx",
  ".xlsx",
  ".mp3",
  ".wav",
  ".m4a",
  ".aac",
  ".ogg",
  ".opus",
  ".flac",
  ".mp4",
  ".mov",
  ".mkv",
  ".webm",
  "application/pdf",
  "text/plain",
  "text/markdown",
  "text/html",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/rtf",
  "text/csv",
  "application/json",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "audio/*",
  "video/*",
].join(",");

/**
 * "Add anything" capture — paste a URL or text, it lands in the brain and
 * (for content with a body) shows the summary + key-moments table once the
 * background job finishes. The web counterpart to the Telegram forward flow.
 */
export function AddAnythingPanel({ onCreated, onError }: AddAnythingPanelProps) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [result, setResult] = useState<Item | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
    if (!trimmed) return;
    setBusy(true);
    setResult(null);
    const isUrl = URL_RE.test(trimmed);
    setStatus(isUrl ? "Fetching and summarizing…" : "Summarizing…");
    try {
      const created = isUrl
        ? await createItem({ source: "url", kind: "article", url: trimmed })
        : await createItem({ source: "paste", kind: "note", body: trimmed });
      onCreated?.(created);
      const finished = await pollForSummary(created.id);
      setResult(finished);
      setValue("");
      setStatus("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't add that.";
      setStatus("");
      onError?.(message);
    } finally {
      setBusy(false);
    }
  }, [value, onCreated, onError, pollForSummary]);

  const handleFile = useCallback(
    async (file: File) => {
      if (busy) return;
      setBusy(true);
      setResult(null);
      setStatus(`Uploading ${file.name}…`);
      try {
        const outcome = await uploadItem(file);
        if (outcome.kind === "recording") {
          // Audio/video go to the transcription pipeline — no Item to poll;
          // it surfaces under Recordings when ready.
          setStatus("Transcribing — it'll appear in your recordings shortly.");
          return;
        }
        const created = outcome.item;
        onCreated?.(created);
        setStatus("Summarizing…");
        const finished = await pollForSummary(created.id);
        setResult(finished);
        setStatus("");
      } catch (err) {
        setStatus("");
        onError?.(err instanceof Error ? err.message : "Couldn't upload that file.");
      } finally {
        setBusy(false);
      }
    },
    [busy, onCreated, onError, pollForSummary],
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
        accept={ACCEPTED_FILE_TYPES}
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
          placeholder="Paste a link or any text — articles, videos, notes…"
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
            {busy ? "Adding…" : "Add to brain"}
          </button>
          <button
            type="button"
            className="add-anything__attach"
            disabled={busy}
            onClick={() => fileInputRef.current?.click()}
          >
            Attach file
          </button>
        </div>
      </div>
      <p className="add-anything__hint">
        Drop a document, audio, or video file here, or paste a link above.
      </p>

      {status ? <p className="add-anything__status">{status}</p> : null}
      {fetchError ? <p className="add-anything__error">{fetchError}</p> : null}

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
