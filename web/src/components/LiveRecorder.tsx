"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { createRecording, saveTranscript } from "@/lib/api";
import { RealtimeTranscriber, type RealtimeState } from "@/lib/realtime";
import type { RecordingDetail } from "@/lib/types";

type Locale = "en" | "ru";

interface Copy {
  start: string;
  connecting: string;
  stop: string;
  saving: string;
  listening: string;
  defaultTitle: () => string;
  micDenied: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    start: "Record in browser",
    connecting: "Connecting…",
    stop: "Stop & save",
    saving: "Saving…",
    listening: "Listening…",
    defaultTitle: () => `Recording ${new Date().toLocaleString()}`,
    micDenied: "Microphone access is required to record.",
  },
  ru: {
    start: "Запись в браузере",
    connecting: "Подключение…",
    stop: "Стоп и сохранить",
    saving: "Сохраняем…",
    listening: "Слушаю…",
    defaultTitle: () => `Запись ${new Date().toLocaleString()}`,
    micDenied: "Для записи нужен доступ к микрофону.",
  },
};

function formatTimer(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
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
  const supportsSystemAudio =
    typeof navigator !== "undefined"
    && typeof navigator.mediaDevices?.getDisplayMedia === "function";
  const transcriberRef = useRef<RealtimeTranscriber | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => () => clearTimer(), [clearTimer]);

  const start = useCallback(async () => {
    setCommitted("");
    setInterim("");
    setSeconds(0);
    setNote(null);
    const streams: MediaStream[] = [];
    try {
      streams.push(await navigator.mediaDevices.getUserMedia({ audio: true }));
    } catch {
      onError(copy.micDenied);
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
          setNote(
            locale === "ru"
              ? "Системное аудио не выбрано — запись только с микрофона."
              : "No system audio was shared — recording mic only.",
          );
        }
      } catch {
        setNote(
          locale === "ru"
            ? "Системное аудио недоступно — запись только с микрофона."
            : "System audio unavailable — recording mic only.",
        );
      }
    }
    const transcriber = new RealtimeTranscriber({
      onState: setState,
      onUpdate: ({ committed: c, interim: i }) => {
        setCommitted(c);
        setInterim(i);
      },
      onError: (message) => {
        clearTimer();
        onError(message);
      },
    });
    transcriberRef.current = transcriber;
    await transcriber.start(streams);
    if (transcriber.getState() === "recording") {
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    }
  }, [clearTimer, copy.micDenied, includeSystem, locale, onError, supportsSystemAudio]);

  const stop = useCallback(async () => {
    clearTimer();
    const transcriber = transcriberRef.current;
    if (!transcriber) return;
    setState("stopping");
    const segments = await transcriber.stop();
    transcriberRef.current = null;
    if (segments.length === 0) {
      // Nothing transcribed — don't create an empty recording.
      setState("idle");
      setSeconds(0);
      setCommitted("");
      setInterim("");
      return;
    }
    try {
      const recording = await createRecording({
        title: copy.defaultTitle(),
        type: "note",
        ...(folderId ? { folder_id: folderId } : {}),
      });
      const detail = await saveTranscript(recording.id, segments);
      onRecordingComplete(detail);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Could not save the recording.");
    } finally {
      setState("idle");
      setSeconds(0);
      setCommitted("");
      setInterim("");
    }
  }, [clearTimer, copy, folderId, onError, onRecordingComplete]);

  const isActive = state === "connecting" || state === "recording" || state === "stopping";

  return (
    <div className="live-recorder" data-testid="live-recorder" data-state={state}>
      {!isActive ? (
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
          {note ? <p className="settings-note">{note}</p> : null}
        </div>
      ) : (
        <div className="live-recorder__active">
          <div className="live-recorder__status">
            {state === "recording" ? (
              <span className="live-recorder__dot" aria-hidden="true" />
            ) : null}
            <span className="mono live-recorder__timer">{formatTimer(seconds)}</span>
            <span className="live-recorder__label">
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
              disabled={state !== "recording"}
            >
              {copy.stop}
            </button>
          </div>
          {committed || interim ? (
            <p className="live-recorder__transcript">
              {committed}
              {interim ? <span className="live-recorder__interim"> {interim}</span> : null}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
