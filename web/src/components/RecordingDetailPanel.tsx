"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createRecordingShareLink,
  exportRecording,
  getRecording,
  startSummaryGeneration,
  updateRecording,
} from "@/lib/api";
import { formatSpeakerLabel } from "@/lib/format";
import type { Folder, RecordingDetail, Segment, Summary } from "@/lib/types";
import { SpeakerChip } from "@/components/SpeakerChip";

type DetailLocale = "en" | "ru";

interface DetailFolderCopy {
  label: string;
  noFolder: string;
}

const FOLDER_COPY: Record<DetailLocale, DetailFolderCopy> = {
  en: { label: "Move to folder", noFolder: "(no folder)" },
  ru: { label: "Переместить в папку", noFolder: "(без папки)" },
};

function formatTimestamp(ms: number | null): string {
  if (ms === null) return "";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

function formatDuration(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function formatError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

function recordingTypeLabel(type: string): string {
  return type.charAt(0).toUpperCase() + type.slice(1);
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [text]);

  return (
    <button className="ghost-button compact-button" type="button" onClick={handleCopy}>
      {copied ? "Copied" : label}
    </button>
  );
}

type Tab = "transcript" | "summary";
type DetailMode = "active" | "trash";

export function RecordingDetailPanel({
  recording,
  mode = "active",
  folders,
  locale = "en",
  onRecordingUpdate,
  onAssignFolder,
  onRestore,
  onDelete,
}: {
  recording: RecordingDetail;
  mode?: DetailMode;
  folders?: Folder[];
  locale?: DetailLocale;
  onRecordingUpdate?: (r: RecordingDetail) => void;
  onAssignFolder?: (recordingId: string, folderId: string | null) => void;
  onRestore?: (recordingId: string) => void;
  onDelete?: (recordingId: string) => void;
}) {
  const folderCopy = FOLDER_COPY[locale] ?? FOLDER_COPY.en;
  const [tab, setTab] = useState<Tab>("transcript");
  const [generating, setGenerating] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [draftTitle, setDraftTitle] = useState(recording.title ?? "");
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<"trash" | "permanent" | null>(null);

  const tabs = useMemo(
    () =>
      [
        ["transcript", "Transcript"],
        ["summary", "Summary"],
      ] as const,
    [],
  );

  useEffect(() => {
    setDraftTitle(recording.title ?? "");
    setRenameOpen(false);
  }, [recording.id, recording.title]);

  const handleGenerateSummary = async (instructions: string | null) => {
    setGenerating(true);
    setError(null);
    setNotice(null);
    try {
      await startSummaryGeneration(recording.id, { instructions });
      const updated = await getRecording(recording.id);
      onRecordingUpdate?.(updated);
      setTab("summary");
      setNotice("Summary generation queued.");
    } catch (e) {
      setError(formatError(e));
    } finally {
      setGenerating(false);
    }
  };

  const handleRename = async () => {
    const nextTitle = draftTitle.trim();
    setRenaming(true);
    setError(null);
    setNotice(null);
    try {
      await updateRecording(recording.id, { title: nextTitle.length > 0 ? nextTitle : null });
      const updated = await getRecording(recording.id);
      onRecordingUpdate?.(updated);
      setRenameOpen(false);
      setNotice("Recording renamed.");
    } catch (e) {
      setError(formatError(e));
    } finally {
      setRenaming(false);
    }
  };

  const handleExport = async (format: "markdown" | "txt" | "srt") => {
    setError(null);
    setNotice(null);
    try {
      const blob = await exportRecording(recording.id, format, { locale });
      const url = URL.createObjectURL(blob);
      const ext = format === "markdown" ? "md" : format;
      const title = recording.title ?? "recording";
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title.replace(/[/\\]/g, "_")}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(formatError(e));
    }
  };

  const handleShare = async () => {
    setSharing(true);
    setError(null);
    setNotice(null);

    try {
      const link = await createRecordingShareLink(recording.id);
      const shareData = {
        title: recording.title ?? "WaiComputer note",
        text: "Shared WaiComputer note",
        url: link.url,
      };

      if (typeof navigator.share === "function") {
        try {
          await navigator.share(shareData);
          setNotice("Share sheet opened.");
          return;
        } catch (e) {
          if (e instanceof DOMException && e.name === "AbortError") {
            setNotice("Share canceled.");
            return;
          }
        }
      }

      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard sharing is unavailable in this browser.");
      }
      await navigator.clipboard.writeText(link.url);
      setNotice("Share link copied.");
    } catch (e) {
      setError(formatError(e));
    } finally {
      setSharing(false);
    }
  };

  return (
    <section className="detail-panel" data-testid="recording-detail">
      <header className="detail-panel__header">
        <div className="detail-panel__title-block">
          {renameOpen ? (
            <div className="inline-title-edit">
              <input
                aria-label="Recording title"
                value={draftTitle}
                onChange={(event) => setDraftTitle(event.target.value)}
                disabled={renaming}
              />
              <button className="ghost-button compact-button" type="button" onClick={handleRename} disabled={renaming}>
                {renaming ? "Saving..." : "Save"}
              </button>
              <button
                className="ghost-button compact-button"
                type="button"
                onClick={() => {
                  setDraftTitle(recording.title ?? "");
                  setRenameOpen(false);
                }}
                disabled={renaming}
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="section-heading-row">
              <h2>{recording.title ?? "(untitled recording)"}</h2>
              {mode === "active" ? (
                <button className="ghost-button compact-button" type="button" onClick={() => setRenameOpen(true)}>
                  Rename
                </button>
              ) : null}
            </div>
          )}
          <div className="metadata-row">
            <span className="type-dot" aria-hidden="true" />
            <span>{recordingTypeLabel(recording.type)}</span>
            <span>{formatDate(recording.created_at)}</span>
            {recording.duration_seconds ? <span>{formatDuration(recording.duration_seconds)}</span> : null}
          </div>
        </div>

        <div className="detail-panel__actions">
          {mode === "active" ? (
            <>
              {folders && onAssignFolder ? (
                <select
                  aria-label={folderCopy.label}
                  title={folderCopy.label}
                  className="select-button"
                  data-testid="assign-folder-select"
                  value={recording.folder_id ?? ""}
                  onChange={(event) => {
                    const next = event.target.value || null;
                    // Optimistic local update so the panel reflects the
                    // assignment immediately; the parent will refetch.
                    onRecordingUpdate?.({ ...recording, folder_id: next });
                    onAssignFolder(recording.id, next);
                  }}
                >
                  <option value="">{folderCopy.noFolder}</option>
                  {folders.map((folder) => (
                    <option key={folder.id} value={folder.id}>
                      {folder.name}
                    </option>
                  ))}
                </select>
              ) : null}
              <button
                className="ghost-button"
                data-testid="share-recording"
                type="button"
                onClick={handleShare}
                disabled={sharing}
              >
                {sharing ? "Sharing..." : "Share"}
              </button>
              <select
                className="select-button"
                aria-label="Export recording"
                onChange={(event) => {
                  if (event.target.value) {
                    void handleExport(event.target.value as "markdown" | "txt" | "srt");
                  }
                  event.target.value = "";
                }}
                defaultValue=""
              >
                <option value="" disabled>
                  Export
                </option>
                <option value="markdown">Markdown</option>
                <option value="txt">Plain Text</option>
                <option value="srt">SRT</option>
              </select>
              {onDelete ? (
                <button
                  className="ghost-button danger-button"
                  type="button"
                  onClick={() => setConfirmDelete("trash")}
                >
                  Move to Trash
                </button>
              ) : null}
            </>
          ) : (
            <>
              <button className="ghost-button" type="button" onClick={() => onRestore?.(recording.id)}>
                Restore
              </button>
              <button
                className="ghost-button danger-button"
                type="button"
                onClick={() => setConfirmDelete("permanent")}
              >
                Delete Permanently
              </button>
            </>
          )}
        </div>
      </header>

      {error ? (
        <p className="inline-alert" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="inline-success" role="status">
          {notice}
        </p>
      ) : null}

      <div className="tab-strip" role="tablist" aria-label="Recording detail">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            id={`recording-tab-${key}`}
            className="tab-button"
            type="button"
            role="tab"
            aria-selected={tab === key}
            aria-controls={`recording-panel-${key}`}
            tabIndex={tab === key ? 0 : -1}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div
        id={`recording-panel-${tab}`}
        className="detail-panel__content"
        role="tabpanel"
        aria-labelledby={`recording-tab-${tab}`}
      >
        {tab === "transcript" && (
          <TranscriptTab
            segments={recording.segments}
            status={recording.status}
            recordingId={recording.id}
            onRecordingUpdate={onRecordingUpdate}
          />
        )}
        {tab === "summary" && (
          <SummaryTab summary={recording.summary} onGenerate={handleGenerateSummary} generating={generating} />
        )}
      </div>

      {confirmDelete ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          data-testid="confirm-delete-recording"
          onClick={(event) => {
            if (event.target === event.currentTarget) setConfirmDelete(null);
          }}
        >
          <div className="modal-card">
            <h3>
              {confirmDelete === "permanent"
                ? "Delete recording permanently?"
                : "Move recording to Trash?"}
            </h3>
            <p>
              {confirmDelete === "permanent"
                ? "This recording, its transcript, and summary will be permanently removed. This cannot be undone."
                : "You can restore it from Trash later."}
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="ghost-button"
                onClick={() => setConfirmDelete(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="ghost-button danger-button"
                data-testid="confirm-delete-recording-action"
                onClick={() => {
                  const target = confirmDelete;
                  setConfirmDelete(null);
                  if (target === "permanent") {
                    onDelete?.(recording.id);
                  } else {
                    onDelete?.(recording.id);
                  }
                }}
              >
                {confirmDelete === "permanent" ? "Delete Permanently" : "Move to Trash"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function TranscriptTab({
  segments,
  status,
  recordingId,
  onRecordingUpdate,
}: {
  segments: Segment[];
  status: string;
  recordingId: string;
  onRecordingUpdate?: (r: RecordingDetail) => void;
}) {
  if (segments.length === 0) {
    if (isRecordingProcessing(status)) {
      return (
        <div className="empty-state">
          <h3>Transcript is processing</h3>
          <p>WaiComputer is processing this recording. The transcript will appear here automatically.</p>
        </div>
      );
    }

    return (
      <div className="empty-state">
        <h3>No Transcript</h3>
        <p>This recording does not have transcript segments yet.</p>
      </div>
    );
  }

  const fullText = segments
    .map((s) => {
      const speaker = formatSpeakerLabel(s.speaker, s.raw_label, s.display_name);
      const ts = formatTimestamp(s.start_ms);
      return `[${speaker}, ${ts}] ${s.content}`;
    })
    .join("\n");

  return (
    <div className="reading-stack">
      <div className="section-heading-row">
        <h3>Transcript</h3>
        <CopyButton text={fullText} label="Copy Transcript" />
      </div>
      {segments.map((segment) => {
        // When the diariser exposes raw machine labels like "speaker_0" /
        // "Speaker 0" but no person has been assigned yet, render a friendly
        // "Speaker 1" label via display_name. raw_label is preserved so the
        // backend assign-speaker call still receives the original token.
        const displaySegment =
          !segment.display_name && !segment.person_id
            ? {
                ...segment,
                display_name: formatSpeakerLabel(
                  segment.speaker,
                  segment.raw_label,
                  null,
                ),
              }
            : segment;
        return (
          <article key={segment.id} className="transcript-row">
            <div className="metadata-row">
              {segment.raw_label || segment.speaker ? (
                <SpeakerChip
                  segment={displaySegment}
                  recordingId={recordingId}
                  onUpdated={(detail) => onRecordingUpdate?.(detail)}
                />
              ) : null}
              <span className="mono">{formatTimestamp(segment.start_ms)}</span>
            </div>
            <p>{segment.content}</p>
          </article>
        );
      })}
    </div>
  );
}

function isRecordingProcessing(status: string) {
  return ["pending_upload", "uploading", "processing"].includes(status);
}

function SummaryTab({
  summary,
  onGenerate,
  generating,
}: {
  summary: Summary | null;
  onGenerate: (instructions: string | null) => void;
  generating: boolean;
}) {
  if (!summary) {
    return (
      <div className="empty-state">
        <h3>No Summary</h3>
        <button
          type="button"
          onClick={() => onGenerate(null)}
          disabled={generating}
        >
          {generating ? "Generating…" : "Generate Summary"}
        </button>
      </div>
    );
  }

  const fullSummaryText = [
    summary.summary,
    summary.key_points?.length ? "\nKey Points:\n" + summary.key_points.map((p) => `- ${p}`).join("\n") : null,
    summary.topics?.length ? "\nTopics: " + summary.topics.join(" · ") : null,
    summary.people_mentioned?.length ? "\nPeople: " + summary.people_mentioned.join(", ") : null,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <div className="reading-stack">
      <div className="section-heading-row">
        <h3>Summary</h3>
        <div className="metadata-row">
          <CopyButton text={fullSummaryText} label="Copy Summary" />
        </div>
      </div>

      {summary.summary ? (
        <section className="note-section">
          <h4>Overview</h4>
          <p>{summary.summary}</p>
        </section>
      ) : null}

      {summary.key_points?.length ? (
        <section className="note-section">
          <h4>Key Points</h4>
          <ul className="reading-list">
            {summary.key_points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {summary.topics?.length ? (
        <section className="note-section">
          <h4>Topics</h4>
          <p className="muted-text">{summary.topics.join(" · ")}</p>
        </section>
      ) : null}

      {summary.people_mentioned?.length ? (
        <section className="note-section">
          <h4>People</h4>
          <p className="muted-text">{summary.people_mentioned.join(", ")}</p>
        </section>
      ) : null}
    </div>
  );
}
