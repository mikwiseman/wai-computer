"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { createRecording, saveTranscript } from "@/lib/api";
import { RealtimeTranscriber, type RealtimeState } from "@/lib/realtime";
import type { RecordingDetail, TranscriptSegmentInput } from "@/lib/types";

type Locale = "en" | "ru";

interface Copy {
  start: string;
  connecting: string;
  stop: string;
  saving: string;
  listening: string;
  defaultTitle: () => string;
  micDenied: string;
  noSpeech: string;
  recordingError: string;
  unsavedTitle: string;
  restoredNote: string;
  retrySave: string;
  discardUnsaved: string;
}

function provisionalRecordingTitle(locale: Locale): string {
  const isRussian = locale === "ru";
  const date = new Intl.DateTimeFormat(isRussian ? "ru-RU" : "en-US", {
    year: "numeric",
    month: isRussian ? "2-digit" : "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: !isRussian,
  }).format(new Date());
  return `${isRussian ? "Запись" : "Recording"} · ${date}`;
}

const COPY: Record<Locale, Copy> = {
  en: {
    start: "Record in browser",
    connecting: "Connecting…",
    stop: "Stop & save",
    saving: "Saving…",
    listening: "Listening…",
    defaultTitle: () => provisionalRecordingTitle("en"),
    micDenied: "Microphone access is required to record.",
    noSpeech: "No speech was captured — nothing to save.",
    recordingError: "Recording stopped unexpectedly. Start again to keep going.",
    unsavedTitle: "This recording isn't saved yet — it's kept in this browser.",
    restoredNote: "An unsaved recording from a previous session was restored.",
    retrySave: "Retry save",
    discardUnsaved: "Discard recording",
  },
  ru: {
    start: "Запись в браузере",
    connecting: "Подключение…",
    stop: "Стоп и сохранить",
    saving: "Сохраняем…",
    listening: "Слушаю…",
    defaultTitle: () => provisionalRecordingTitle("ru"),
    micDenied: "Для записи нужен доступ к микрофону.",
    noSpeech: "Речь не распознана — сохранять нечего.",
    recordingError: "Запись неожиданно остановилась. Начните заново, чтобы продолжить.",
    unsavedTitle: "Запись ещё не сохранена — она хранится в этом браузере.",
    restoredNote: "Восстановлена несохранённая запись из прошлой сессии.",
    retrySave: "Сохранить ещё раз",
    discardUnsaved: "Удалить запись",
  },
};

/** Unsaved stop-result persisted to localStorage so a failed save (network
 *  blip, backend error, tab crash mid-save) never loses captured speech. */
interface PendingLiveRecording {
  title: string;
  folderId: string | null;
  segments: TranscriptSegmentInput[];
  /** Set once createRecording succeeded, so retries reuse the recording
   *  instead of creating duplicates. */
  recordingId?: string;
}

const PENDING_STORAGE_KEY = "wai:live-recorder:pending";

function readPendingFromStorage(): PendingLiveRecording | null {
  try {
    const raw = localStorage.getItem(PENDING_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PendingLiveRecording;
    if (!Array.isArray(parsed.segments) || parsed.segments.length === 0) return null;
    if (typeof parsed.title !== "string") return null;
    return parsed;
  } catch {
    return null;
  }
}

function writePendingToStorage(payload: PendingLiveRecording | null): void {
  try {
    if (payload) {
      localStorage.setItem(PENDING_STORAGE_KEY, JSON.stringify(payload));
    } else {
      localStorage.removeItem(PENDING_STORAGE_KEY);
    }
  } catch {
    // Storage full/blocked — the in-memory retry UI still protects this tab.
  }
}

function formatTimer(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

function stopMediaStream(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}

function stopMediaStreams(streams: MediaStream[]): void {
  streams.forEach(stopMediaStream);
}

function reportRealtimeCleanupError(error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  if (typeof console !== "undefined") {
    console.warn("Realtime transcription cleanup failed:", message);
  }
}

interface LiveRecorderProps {
  onRecordingComplete: (detail: RecordingDetail) => void;
  onError: (message: string) => void;
  locale?: Locale;
  folderId?: string | null;
}

export function LiveRecorder({
  onRecordingComplete,
  onError,
  locale = "en",
  folderId = null,
}: LiveRecorderProps) {
  const copy = COPY[locale];
  const [state, setState] = useState<RealtimeState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [committed, setCommitted] = useState("");
  const [interim, setInterim] = useState("");
  const [includeSystem, setIncludeSystem] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [pendingSave, setPendingSave] = useState<PendingLiveRecording | null>(null);
  const [savingPending, setSavingPending] = useState(false);
  const supportsSystemAudio =
    typeof navigator !== "undefined"
    && typeof navigator.mediaDevices?.getDisplayMedia === "function";
  const transcriberRef = useRef<RealtimeTranscriber | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const teardownTranscriber = useCallback(() => {
    clearTimer();
    const transcriber = transcriberRef.current;
    transcriberRef.current = null;
    if (!transcriber) return;
    void transcriber.stop().catch(reportRealtimeCleanupError);
  }, [clearTimer]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      teardownTranscriber();
    };
  }, [teardownTranscriber]);

  // Restore an unsaved recording from a previous session (tab closed or
  // crashed between stop and a successful save).
  useEffect(() => {
    const restored = readPendingFromStorage();
    if (!restored) return;
    setPendingSave(restored);
    setNote(copy.restoredNote);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const performPendingSave = useCallback(
    async (payload: PendingLiveRecording): Promise<boolean> => {
      setSavingPending(true);
      try {
        let recordingId = payload.recordingId;
        if (!recordingId) {
          const recording = await createRecording({
            title: payload.title,
            title_mode: "automatic",
            type: "note",
            ...(payload.folderId ? { folder_id: payload.folderId } : {}),
          });
          recordingId = recording.id;
          // Remember the created recording immediately so a retry after a
          // failed transcript save reuses it instead of duplicating.
          const claimed = { ...payload, recordingId };
          setPendingSave(claimed);
          writePendingToStorage(claimed);
        }
        const detail = await saveTranscript(recordingId, payload.segments);
        setPendingSave(null);
        writePendingToStorage(null);
        if (mountedRef.current) setNote(null);
        onRecordingComplete(detail);
        return true;
      } catch (error) {
        if (mountedRef.current) {
          onError(error instanceof Error ? error.message : "Could not save the recording.");
        }
        return false;
      } finally {
        if (mountedRef.current) setSavingPending(false);
      }
    },
    [onError, onRecordingComplete],
  );

  const start = useCallback(async () => {
    setCommitted("");
    setInterim("");
    setSeconds(0);
    setNote(null);
    setLiveError(null);
    const streams: MediaStream[] = [];
    try {
      streams.push(await navigator.mediaDevices.getUserMedia({ audio: true }));
    } catch {
      onError(copy.micDenied);
      return;
    }
    if (!mountedRef.current) {
      stopMediaStreams(streams);
      return;
    }
    if (includeSystem && supportsSystemAudio) {
      try {
        // getDisplayMedia needs video:true to expose the "share tab/screen
        // audio" checkbox in Chromium; we keep only the audio track.
        const display = await navigator.mediaDevices.getDisplayMedia({
          video: true,
          audio: true,
        });
        display.getVideoTracks().forEach((track) => track.stop());
        const audioTracks = display.getAudioTracks();
        if (audioTracks.length > 0) {
          streams.push(new MediaStream(audioTracks));
        } else {
          if (!mountedRef.current) {
            stopMediaStreams(streams);
            return;
          }
          setNote(
            locale === "ru"
              ? "Системное аудио не выбрано — запись только с микрофона."
              : "No system audio was shared — recording mic only.",
          );
        }
      } catch {
        if (!mountedRef.current) {
          stopMediaStreams(streams);
          return;
        }
        setNote(
          locale === "ru"
            ? "Системное аудио недоступно — запись только с микрофона."
            : "System audio unavailable — recording mic only.",
        );
      }
    }
    if (!mountedRef.current) {
      stopMediaStreams(streams);
      return;
    }
    const transcriber = new RealtimeTranscriber({
      onState: (nextState) => {
        if (mountedRef.current) setState(nextState);
      },
      onUpdate: ({ committed: c, interim: i }) => {
        if (!mountedRef.current) return;
        setCommitted(c);
        setInterim(i);
      },
      onError: () => {
        if (!mountedRef.current) return;
        clearTimer();
        // Surface the drop inline and keep the visible transcript, instead of
        // bubbling to the parent (which swaps this recorder out and discards the
        // on-screen transcript). The transcriber has already cleaned up its
        // socket by the time this fires.
        setLiveError(copy.recordingError);
      },
    });
    transcriberRef.current = transcriber;
    await transcriber.start(streams);
    if (
      mountedRef.current &&
      transcriberRef.current === transcriber &&
      transcriber.getState() === "recording"
    ) {
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    }
  }, [clearTimer, copy.micDenied, copy.recordingError, includeSystem, locale, onError, supportsSystemAudio]);

  const stop = useCallback(async () => {
    clearTimer();
    const transcriber = transcriberRef.current;
    if (!transcriber) return;
    transcriberRef.current = null;
    setState("stopping");
    let segments: TranscriptSegmentInput[];
    try {
      segments = await transcriber.stop();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Could not finalize the recording.");
      setState("idle");
      setSeconds(0);
      setCommitted("");
      setInterim("");
      return;
    }
    if (segments.length === 0) {
      // Nothing transcribed — don't create an empty recording, but say why
      // nothing was saved instead of silently snapping back to idle.
      setState("idle");
      setSeconds(0);
      setCommitted("");
      setInterim("");
      setNote(copy.noSpeech);
      return;
    }
    // Persist BEFORE attempting the save: a network blip or crash mid-save
    // must never lose captured speech (the browser has no other backup).
    const payload: PendingLiveRecording = {
      title: copy.defaultTitle(),
      folderId,
      segments,
    };
    setPendingSave(payload);
    writePendingToStorage(payload);
    const saved = await performPendingSave(payload);
    if (!mountedRef.current) return;
    setState("idle");
    setSeconds(0);
    setInterim("");
    if (saved) {
      setCommitted("");
    }
    // On failure the transcript stays visible next to the retry button.
  }, [clearTimer, copy, folderId, onError, performPendingSave]);

  const isActive = state === "connecting" || state === "recording" || state === "stopping";

  return (
    <div className="live-recorder" data-testid="live-recorder" data-state={state}>
      {liveError ? (
        <div className="live-recorder__active">
          <p className="inline-alert" role="alert">{liveError}</p>
          {committed ? (
            <div className="live-recorder__transcript">
              <p aria-live="polite">{committed}</p>
            </div>
          ) : null}
          <button type="button" className="live-recorder__start" onClick={() => void start()}>
            {copy.start}
          </button>
        </div>
      ) : pendingSave && !isActive ? (
        <div className="live-recorder__active" data-testid="live-recorder-unsaved">
          <p className="inline-alert" role="alert">
            {copy.unsavedTitle}
          </p>
          <div className="live-recorder__transcript">
            <p>
              {committed || pendingSave.segments.map((segment) => segment.text).join(" ")}
            </p>
          </div>
          <div className="button-row">
            <button
              type="button"
              className="live-recorder__start"
              data-testid="live-recorder-retry-save"
              disabled={savingPending}
              onClick={() => void performPendingSave(pendingSave)}
            >
              {savingPending ? copy.saving : copy.retrySave}
            </button>
            <button
              type="button"
              className="ghost-button"
              data-testid="live-recorder-discard-unsaved"
              disabled={savingPending}
              onClick={() => {
                setPendingSave(null);
                writePendingToStorage(null);
                setCommitted("");
                setNote(null);
              }}
            >
              {copy.discardUnsaved}
            </button>
          </div>
          {note ? <p className="settings-note" role="status">{note}</p> : null}
        </div>
      ) : !isActive ? (
        <div className="live-recorder__idle">
          <button type="button" className="live-recorder__start" onClick={() => void start()}>
            {copy.start}
          </button>
          {supportsSystemAudio ? (
            <label className="live-recorder__option">
              <input
                type="checkbox"
                checked={includeSystem}
                onChange={(event) => setIncludeSystem(event.target.checked)}
              />
              <span>
                {locale === "ru"
                  ? "Захватывать системное аудио (Chrome/Edge)"
                  : "Capture system audio (Chrome/Edge)"}
              </span>
            </label>
          ) : null}
          {note ? <p className="settings-note" role="status">{note}</p> : null}
        </div>
      ) : (
        <div className="live-recorder__active">
          <div className="live-recorder__status">
            {state === "recording" ? (
              <span className="live-recorder__dot" aria-hidden="true" />
            ) : null}
            <span className="mono live-recorder__timer">{formatTimer(seconds)}</span>
            <span className="live-recorder__label" aria-live="polite">
              {state === "connecting"
                ? copy.connecting
                : state === "stopping"
                  ? copy.saving
                  : copy.listening}
            </span>
            <button
              type="button"
              className="ghost-button compact-button danger-button"
              onClick={() => void stop()}
              disabled={state !== "connecting" && state !== "recording"}
            >
              {copy.stop}
            </button>
          </div>
          {committed || interim ? (
            <div className="live-recorder__transcript">
              {committed ? <p aria-live="polite">{committed}</p> : null}
              {interim ? (
                <span className="live-recorder__interim" aria-hidden="true">
                  {interim}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
