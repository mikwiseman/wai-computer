"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createRecordingShareLink,
  downloadRecordingSummaryAudio,
  exportRecording,
  getRecording,
  rematchSpeakers,
  startRecordingSummaryAudio,
  startSummaryGeneration,
  updateRecording,
} from "@/lib/api";
import { formatSpeakerLabel, formatTimestamp } from "@/lib/format";
import { mergeTurns, renderTranscript } from "@/lib/transcript";
import type {
  Folder,
  RecordingDetail,
  Segment,
  Summary,
  SummaryAudio,
  SummaryGeneration,
} from "@/lib/types";
import { SpeakerChip } from "@/components/SpeakerChip";
import { SummaryAudioControls } from "@/components/SummaryAudioControls";

type DetailLocale = "en" | "ru";
const automaticSummaryStartKeys = new Set<string>();

interface DetailCopy {
  folderLabel: string;
  noFolder: string;
  unexpectedError: string;
  copied: string;
  tabTranscript: string;
  tabSummary: string;
  summaryQueued: string;
  summaryAudioQueued: string;
  renamed: string;
  shareTitle: string;
  shareText: string;
  shareOpened: string;
  shareCanceled: string;
  clipboardUnavailable: string;
  shareCopied: string;
  recordingTitleLabel: string;
  saving: string;
  save: string;
  cancel: string;
  untitled: string;
  rename: string;
  sharing: string;
  share: string;
  rematching: string;
  rematch: string;
  exportLabel: string;
  exportPlaceholder: string;
  plainText: string;
  moveToTrash: string;
  restore: string;
  deletePermanently: string;
  detailLabel: string;
  confirmDeletePermTitle: string;
  confirmDeleteTrashTitle: string;
  confirmDeletePermBody: string;
  confirmDeleteTrashBody: string;
  transcriptProcessingTitle: string;
  transcriptProcessingBody: string;
  noTranscriptTitle: string;
  noTranscriptBody: string;
  transcriptHeading: string;
  copyTranscript: string;
  copyWithTimestamps: string;
  plainTextTimestamped: string;
  noSummaryTitle: string;
  noSummaryBody: string;
  summaryStartingTitle: string;
  summaryPendingTitle: string;
  summaryPendingBody: string;
  summaryFailedTitle: string;
  summaryStartFailedBody: string;
  retrySummary: string;
  summaryProgressLabel: string;
  generating: string;
  summaryHeading: string;
  copySummary: string;
  overview: string;
  keyPoints: string;
  topics: string;
  people: string;
}

const COPY: Record<DetailLocale, DetailCopy> = {
  en: {
    folderLabel: "Move to folder",
    noFolder: "(no folder)",
    unexpectedError: "Unexpected error",
    copied: "Copied",
    tabTranscript: "Transcript",
    tabSummary: "Summary",
    summaryQueued: "Summary generation queued.",
    summaryAudioQueued: "Summary audio generation queued.",
    renamed: "Recording renamed.",
    shareTitle: "WaiComputer note",
    shareText: "Shared WaiComputer note",
    shareOpened: "Share sheet opened.",
    shareCanceled: "Share canceled.",
    clipboardUnavailable: "Clipboard sharing is unavailable in this browser.",
    shareCopied: "Share link copied.",
    recordingTitleLabel: "Recording title",
    saving: "Saving...",
    save: "Save",
    cancel: "Cancel",
    untitled: "(untitled recording)",
    rename: "Rename",
    sharing: "Sharing...",
    share: "Share",
    rematching: "Re-matching…",
    rematch: "Re-match speakers",
    exportLabel: "Export recording",
    exportPlaceholder: "Export",
    plainText: "Plain Text",
    moveToTrash: "Move to Trash",
    restore: "Restore",
    deletePermanently: "Delete Permanently",
    detailLabel: "Recording detail",
    confirmDeletePermTitle: "Delete recording permanently?",
    confirmDeleteTrashTitle: "Move recording to Trash?",
    confirmDeletePermBody:
      "This recording, its transcript, and summary will be permanently removed. This cannot be undone.",
    confirmDeleteTrashBody: "You can restore it from Trash later.",
    transcriptProcessingTitle: "Transcript is processing",
    transcriptProcessingBody:
      "WaiComputer is processing this recording. The transcript will appear here automatically.",
    noTranscriptTitle: "No Transcript",
    noTranscriptBody: "This recording does not have transcript segments yet.",
    transcriptHeading: "Transcript",
    copyTranscript: "Copy Transcript",
    copyWithTimestamps: "Copy with timestamps",
    plainTextTimestamped: "Plain Text + timestamps",
    noSummaryTitle: "Summary unavailable",
    noSummaryBody: "A transcript is required before WaiComputer can summarize this recording.",
    summaryStartingTitle: "Summary generation is starting",
    summaryPendingTitle: "Summary is being generated",
    summaryPendingBody: "It will appear here automatically when ready.",
    summaryFailedTitle: "Summary generation failed",
    summaryStartFailedBody: "Summary generation could not start.",
    retrySummary: "Retry",
    summaryProgressLabel: "Summary generation progress",
    generating: "Generating…",
    summaryHeading: "Summary",
    copySummary: "Copy Summary",
    overview: "Overview",
    keyPoints: "Key Points",
    topics: "Topics",
    people: "People",
  },
  ru: {
    folderLabel: "Переместить в папку",
    noFolder: "(без папки)",
    unexpectedError: "Непредвиденная ошибка",
    copied: "Скопировано",
    tabTranscript: "Расшифровка",
    tabSummary: "Резюме",
    summaryQueued: "Генерация резюме поставлена в очередь.",
    summaryAudioQueued: "Генерация аудио-резюме поставлена в очередь.",
    renamed: "Запись переименована.",
    shareTitle: "Заметка WaiComputer",
    shareText: "Заметка из WaiComputer",
    shareOpened: "Меню «Поделиться» открыто.",
    shareCanceled: "Отправка отменена.",
    clipboardUnavailable: "Доступ к буферу обмена недоступен в этом браузере.",
    shareCopied: "Ссылка скопирована.",
    recordingTitleLabel: "Название записи",
    saving: "Сохранение...",
    save: "Сохранить",
    cancel: "Отмена",
    untitled: "(запись без названия)",
    rename: "Переименовать",
    sharing: "Отправка...",
    share: "Поделиться",
    rematching: "Сопоставление…",
    rematch: "Сопоставить голоса",
    exportLabel: "Экспорт записи",
    exportPlaceholder: "Экспорт",
    plainText: "Обычный текст",
    moveToTrash: "В корзину",
    restore: "Восстановить",
    deletePermanently: "Удалить навсегда",
    detailLabel: "Детали записи",
    confirmDeletePermTitle: "Удалить запись навсегда?",
    confirmDeleteTrashTitle: "Переместить запись в корзину?",
    confirmDeletePermBody:
      "Запись, её расшифровка и резюме будут удалены навсегда. Это действие необратимо.",
    confirmDeleteTrashBody: "Позже её можно восстановить из корзины.",
    transcriptProcessingTitle: "Расшифровка обрабатывается",
    transcriptProcessingBody:
      "WaiComputer обрабатывает эту запись. Расшифровка появится здесь автоматически.",
    noTranscriptTitle: "Нет расшифровки",
    noTranscriptBody: "У этой записи пока нет сегментов расшифровки.",
    transcriptHeading: "Расшифровка",
    copyTranscript: "Скопировать расшифровку",
    copyWithTimestamps: "Скопировать с тайм-кодами",
    plainTextTimestamped: "Текст с тайм-кодами",
    noSummaryTitle: "Резюме недоступно",
    noSummaryBody: "Для резюме нужна расшифровка этой записи.",
    summaryStartingTitle: "Генерация резюме запускается",
    summaryPendingTitle: "Резюме генерируется",
    summaryPendingBody: "Оно появится здесь автоматически, когда будет готово.",
    summaryFailedTitle: "Генерация резюме не удалась",
    summaryStartFailedBody: "Не удалось запустить генерацию резюме.",
    retrySummary: "Повторить",
    summaryProgressLabel: "Прогресс генерации резюме",
    generating: "Генерация…",
    summaryHeading: "Резюме",
    copySummary: "Скопировать резюме",
    overview: "Обзор",
    keyPoints: "Ключевые тезисы",
    topics: "Темы",
    people: "Люди",
  },
};

function formatDuration(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function formatError(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message;
  return fallback;
}

function recordingTypeLabel(type: string): string {
  return type.charAt(0).toUpperCase() + type.slice(1);
}

function automaticSummaryStartKey(recording: RecordingDetail): string {
  const transcriptSignature = recording.segments
    .map((segment) =>
      [
        segment.id,
        segment.start_ms ?? "",
        segment.end_ms ?? "",
        segment.content.length,
      ].join(":"),
    )
    .join("|");
  return `${recording.id}:${transcriptSignature}`;
}

function CopyButton({ text, label, copiedLabel }: { text: string; label: string; copiedLabel: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [text]);

  return (
    <button className="ghost-button compact-button" type="button" onClick={handleCopy}>
      {copied ? copiedLabel : label}
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
  const copy = COPY[locale] ?? COPY.en;
  const [tab, setTab] = useState<Tab>("transcript");
  const [generating, setGenerating] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [draftTitle, setDraftTitle] = useState(recording.title ?? "");
  const [sharing, setSharing] = useState(false);
  const [rematching, setRematching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<"trash" | "permanent" | null>(null);
  const [autoSummaryStartFailedKey, setAutoSummaryStartFailedKey] = useState<string | null>(null);
  const autoSummaryStartKey = useMemo(
    () => automaticSummaryStartKey(recording),
    [recording],
  );

  const tabs = useMemo(
    () =>
      [
        ["transcript", copy.tabTranscript],
        ["summary", copy.tabSummary],
      ] as const,
    [copy.tabTranscript, copy.tabSummary],
  );

  useEffect(() => {
    setDraftTitle(recording.title ?? "");
    setRenameOpen(false);
  }, [recording.id, recording.title]);

  const handleGenerateSummary = useCallback(async (
    instructions: string | null,
    options: { revealSummaryTab?: boolean; showNotice?: boolean; automatic?: boolean } = {},
  ) => {
    const revealSummaryTab = options.revealSummaryTab ?? true;
    const showNotice = options.showNotice ?? true;
    setGenerating(true);
    setError(null);
    setNotice(null);
    try {
      await startSummaryGeneration(recording.id, { instructions });
      const updated = await getRecording(recording.id);
      onRecordingUpdate?.(updated);
      if (options.automatic) setAutoSummaryStartFailedKey(null);
      if (revealSummaryTab) setTab("summary");
      if (showNotice) setNotice(copy.summaryQueued);
    } catch (e) {
      if (options.automatic) setAutoSummaryStartFailedKey(autoSummaryStartKey);
      setError(formatError(e, copy.unexpectedError));
    } finally {
      setGenerating(false);
    }
  }, [
    autoSummaryStartKey,
    copy.summaryQueued,
    copy.unexpectedError,
    onRecordingUpdate,
    recording.id,
  ]);

  const shouldAutoStartSummary =
    mode === "active" &&
    recording.status === "ready" &&
    recording.segments.length > 0 &&
    recording.summary === null &&
    (recording.summary_generation?.status ?? "not_started") === "not_started";

  useEffect(() => {
    if (!shouldAutoStartSummary || automaticSummaryStartKeys.has(autoSummaryStartKey)) return;
    automaticSummaryStartKeys.add(autoSummaryStartKey);
    void handleGenerateSummary(null, {
      automatic: true,
      revealSummaryTab: false,
      showNotice: true,
    });
  }, [
    autoSummaryStartKey,
    handleGenerateSummary,
    shouldAutoStartSummary,
  ]);

  const handleCreateSummaryAudio = async () => {
    setError(null);
    setNotice(null);
    try {
      await startRecordingSummaryAudio(recording.id);
      const updated = await getRecording(recording.id);
      onRecordingUpdate?.(updated);
      setNotice(copy.summaryAudioQueued);
    } catch (e) {
      setError(formatError(e, copy.unexpectedError));
    }
  };

  const handleDownloadSummaryAudio = async () => {
    try {
      return await downloadRecordingSummaryAudio(recording.id);
    } catch (e) {
      setError(formatError(e, copy.unexpectedError));
      throw e;
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
      setNotice(copy.renamed);
    } catch (e) {
      setError(formatError(e, copy.unexpectedError));
    } finally {
      setRenaming(false);
    }
  };

  const handleExport = async (
    format: "markdown" | "txt" | "srt",
    style?: "timestamped",
  ) => {
    setError(null);
    setNotice(null);
    try {
      const blob = await exportRecording(recording.id, format, { locale, style });
      const url = URL.createObjectURL(blob);
      const ext = format === "markdown" ? "md" : format;
      const title = recording.title ?? "recording";
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title.replace(/[/\\]/g, "_")}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(formatError(e, copy.unexpectedError));
    }
  };

  const handleShare = async () => {
    setSharing(true);
    setError(null);
    setNotice(null);

    try {
      const link = await createRecordingShareLink(recording.id);
      const shareData = {
        title: recording.title ?? copy.shareTitle,
        text: copy.shareText,
        url: link.url,
      };

      if (typeof navigator.share === "function") {
        try {
          await navigator.share(shareData);
          setNotice(copy.shareOpened);
          return;
        } catch (e) {
          if (e instanceof DOMException && e.name === "AbortError") {
            setNotice(copy.shareCanceled);
            return;
          }
        }
      }

      if (!navigator.clipboard?.writeText) {
        throw new Error(copy.clipboardUnavailable);
      }
      await navigator.clipboard.writeText(link.url);
      setNotice(copy.shareCopied);
    } catch (e) {
      setError(formatError(e, copy.unexpectedError));
    } finally {
      setSharing(false);
    }
  };

  const handleRematch = async () => {
    setRematching(true);
    setError(null);
    setNotice(null);
    try {
      const result = await rematchSpeakers(recording.id);
      const updated = await getRecording(recording.id);
      onRecordingUpdate?.(updated);
      setNotice(
        locale === "ru"
          ? `Сопоставление голосов завершено — сопоставлено ${result.matched_clusters} из ${result.updated_clusters}.`
          : `Voice re-match complete — ${result.matched_clusters} of ${result.updated_clusters} ` +
              `speaker${result.updated_clusters === 1 ? "" : "s"} matched.`,
      );
    } catch (e) {
      setError(formatError(e, copy.unexpectedError));
    } finally {
      setRematching(false);
    }
  };

  return (
    <section className="detail-panel" data-testid="recording-detail">
      <header className="detail-panel__header">
        <div className="detail-panel__title-block">
          {renameOpen ? (
            <div className="inline-title-edit">
              <input
                aria-label={copy.recordingTitleLabel}
                value={draftTitle}
                onChange={(event) => setDraftTitle(event.target.value)}
                disabled={renaming}
              />
              <button className="ghost-button compact-button" type="button" onClick={handleRename} disabled={renaming}>
                {renaming ? copy.saving : copy.save}
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
                {copy.cancel}
              </button>
            </div>
          ) : (
            <div className="section-heading-row">
              <h2>{recording.title ?? copy.untitled}</h2>
              {mode === "active" ? (
                <button className="ghost-button compact-button" type="button" onClick={() => setRenameOpen(true)}>
                  {copy.rename}
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
                  aria-label={copy.folderLabel}
                  title={copy.folderLabel}
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
                  <option value="">{copy.noFolder}</option>
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
                {sharing ? copy.sharing : copy.share}
              </button>
              {recording.segments.length > 0 ? (
                <button
                  className="ghost-button"
                  data-testid="rematch-speakers"
                  type="button"
                  onClick={handleRematch}
                  disabled={rematching}
                >
                  {rematching ? copy.rematching : copy.rematch}
                </button>
              ) : null}
              <select
                className="select-button"
                aria-label={copy.exportLabel}
                onChange={(event) => {
                  const value = event.target.value;
                  if (value === "txt-timestamped") {
                    void handleExport("txt", "timestamped");
                  } else if (value) {
                    void handleExport(value as "markdown" | "txt" | "srt");
                  }
                  event.target.value = "";
                }}
                defaultValue=""
              >
                <option value="" disabled>
                  {copy.exportPlaceholder}
                </option>
                <option value="markdown">Markdown</option>
                <option value="txt">{copy.plainText}</option>
                <option value="txt-timestamped">{copy.plainTextTimestamped}</option>
                <option value="srt">SRT</option>
              </select>
              {onDelete ? (
                <button
                  className="ghost-button danger-button"
                  type="button"
                  onClick={() => setConfirmDelete("trash")}
                >
                  {copy.moveToTrash}
                </button>
              ) : null}
            </>
          ) : (
            <>
              <button className="ghost-button" type="button" onClick={() => onRestore?.(recording.id)}>
                {copy.restore}
              </button>
              <button
                className="ghost-button danger-button"
                type="button"
                onClick={() => setConfirmDelete("permanent")}
              >
                {copy.deletePermanently}
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

      <div className="tab-strip" role="tablist" aria-label={copy.detailLabel}>
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
            copy={copy}
          />
        )}
        {tab === "summary" && (
          <SummaryTab
            recording={recording}
            summary={recording.summary}
            summaryGeneration={recording.summary_generation ?? null}
            summaryAutoStartFailed={autoSummaryStartFailedKey === autoSummaryStartKey}
            summaryAudio={recording.summary_audio}
            hasTranscript={recording.segments.length > 0}
            onGenerate={handleGenerateSummary}
            generating={generating}
            onCreateAudio={handleCreateSummaryAudio}
            onDownloadAudio={handleDownloadSummaryAudio}
            copy={copy}
          />
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
                ? copy.confirmDeletePermTitle
                : copy.confirmDeleteTrashTitle}
            </h3>
            <p>
              {confirmDelete === "permanent"
                ? copy.confirmDeletePermBody
                : copy.confirmDeleteTrashBody}
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="ghost-button"
                onClick={() => setConfirmDelete(null)}
              >
                {copy.cancel}
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
                {confirmDelete === "permanent" ? copy.deletePermanently : copy.moveToTrash}
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
  copy,
}: {
  segments: Segment[];
  status: string;
  recordingId: string;
  onRecordingUpdate?: (r: RecordingDetail) => void;
  copy: DetailCopy;
}) {
  if (segments.length === 0) {
    if (isRecordingProcessing(status)) {
      return (
        <div className="empty-state">
          <h3>{copy.transcriptProcessingTitle}</h3>
          <p>{copy.transcriptProcessingBody}</p>
        </div>
      );
    }

    return (
      <div className="empty-state">
        <h3>{copy.noTranscriptTitle}</h3>
        <p>{copy.noTranscriptBody}</p>
      </div>
    );
  }

  // Merge consecutive same-speaker utterances into turns once: this drives both the
  // reading view (one card per turn) and the copy buttons — plain prose by default,
  // timestamped on demand.
  const turns = mergeTurns(segments);
  const plainText = renderTranscript(turns, "plain");
  const timestampedText = renderTranscript(turns, "timestamped");

  return (
    <div className="reading-stack">
      <div className="section-heading-row">
        <h3>{copy.transcriptHeading}</h3>
        <div className="button-row">
          <CopyButton text={plainText} label={copy.copyTranscript} copiedLabel={copy.copied} />
          <CopyButton
            text={timestampedText}
            label={copy.copyWithTimestamps}
            copiedLabel={copy.copied}
          />
        </div>
      </div>
      {turns.map((turn) => {
        const head = turn.segments[0];
        if (!head) return null;
        // When the diariser exposes raw machine labels like "speaker_0" but no
        // person is assigned yet, render a friendly "Speaker 1" via display_name.
        // raw_label is preserved so the backend assign-speaker call still receives
        // the original token (assigning relabels the whole turn).
        const chipSegment =
          !head.display_name && !head.person_id
            ? {
                ...head,
                display_name: formatSpeakerLabel(head.speaker, head.raw_label, null),
              }
            : head;
        return (
          <article key={head.id} className="transcript-row">
            <div className="metadata-row">
              {head.raw_label || head.speaker ? (
                <SpeakerChip
                  segment={chipSegment}
                  recordingId={recordingId}
                  onUpdated={(detail) => onRecordingUpdate?.(detail)}
                />
              ) : null}
              <span className="mono">{formatTimestamp(turn.startMs)}</span>
            </div>
            <p>{turn.text}</p>
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
  recording,
  summary,
  summaryGeneration,
  summaryAutoStartFailed,
  summaryAudio,
  hasTranscript,
  onGenerate,
  generating,
  onCreateAudio,
  onDownloadAudio,
  copy,
}: {
  recording: RecordingDetail;
  summary: Summary | null;
  summaryGeneration: SummaryGeneration | null;
  summaryAutoStartFailed: boolean;
  summaryAudio: SummaryAudio | null | undefined;
  hasTranscript: boolean;
  onGenerate: (instructions: string | null) => void;
  generating: boolean;
  onCreateAudio: () => Promise<void>;
  onDownloadAudio: () => Promise<Blob>;
  copy: DetailCopy;
}) {
  if (!summary) {
    const status = summaryGeneration?.status ?? "not_started";
    const isActive = generating || status === "queued" || status === "running";
    const isFailed = status === "failed";
    const progress = Math.max(
      0,
      Math.min(100, summaryGeneration?.progress_percent ?? (generating ? 5 : 0)),
    );
    const statusMessage =
      summaryGeneration?.message ||
      (generating ? copy.summaryStartingTitle : copy.summaryPendingBody);

    if (isActive) {
      return (
        <div className="empty-state summary-generation-state" role="status">
          <h3>{generating && status === "not_started" ? copy.summaryStartingTitle : copy.summaryPendingTitle}</h3>
          <p>{statusMessage}</p>
          <div className="summary-generation-progress">
            <progress
              aria-label={copy.summaryProgressLabel}
              max={100}
              value={progress}
            />
            <span className="muted-text">{progress}%</span>
          </div>
          <p className="muted-text">{copy.summaryPendingBody}</p>
        </div>
      );
    }

    if (isFailed) {
      return (
        <div className="empty-state summary-generation-state" role="alert">
          <h3>{copy.summaryFailedTitle}</h3>
          <p>{summaryGeneration?.error_message || summaryGeneration?.message || copy.summaryStartFailedBody}</p>
          <button type="button" onClick={() => onGenerate(null)} disabled={generating}>
            {generating ? copy.generating : copy.retrySummary}
          </button>
        </div>
      );
    }

    if (hasTranscript) {
      return (
        <div
          className="empty-state summary-generation-state"
          role={summaryAutoStartFailed ? "alert" : "status"}
        >
          <h3>{summaryAutoStartFailed ? copy.summaryFailedTitle : copy.summaryStartingTitle}</h3>
          <p>{summaryAutoStartFailed ? copy.summaryStartFailedBody : copy.summaryPendingBody}</p>
          {summaryAutoStartFailed ? (
            <button type="button" onClick={() => onGenerate(null)} disabled={generating}>
              {generating ? copy.generating : copy.retrySummary}
            </button>
          ) : null}
        </div>
      );
    }

    return (
      <div className="empty-state">
        <h3>{copy.noSummaryTitle}</h3>
        <p>{copy.noSummaryBody}</p>
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
        <h3>{copy.summaryHeading}</h3>
        <div className="metadata-row">
          <CopyButton text={fullSummaryText} label={copy.copySummary} copiedLabel={copy.copied} />
        </div>
      </div>
      <SummaryAudioControls
        state={summaryAudio}
        onCreate={onCreateAudio}
        onDownload={onDownloadAudio}
        filename={`${(recording.title ?? "summary").replace(/[/\\]/g, "_")}-summary.mp3`}
      />

      {summary.summary ? (
        <section className="note-section">
          <h4>{copy.overview}</h4>
          <p>{summary.summary}</p>
        </section>
      ) : null}

      {summary.key_points?.length ? (
        <section className="note-section">
          <h4>{copy.keyPoints}</h4>
          <ul className="reading-list">
            {summary.key_points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {summary.topics?.length ? (
        <section className="note-section">
          <h4>{copy.topics}</h4>
          <p className="muted-text">{summary.topics.join(" · ")}</p>
        </section>
      ) : null}

      {summary.people_mentioned?.length ? (
        <section className="note-section">
          <h4>{copy.people}</h4>
          <p className="muted-text">{summary.people_mentioned.join(", ")}</p>
        </section>
      ) : null}
    </div>
  );
}
