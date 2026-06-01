"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  cleanupDictation,
  createDictationEntry,
  listDictionaryWords,
} from "@/lib/api";
import { RealtimeTranscriber, type RealtimeState } from "@/lib/realtime";
import type { DictationDictionaryWord } from "@/lib/types";

type Locale = "en" | "ru";

interface Copy {
  heading: string;
  intro: string;
  start: string;
  connecting: string;
  listening: string;
  stop: string;
  cleaning: string;
  copied: string;
  copyAgain: string;
  again: string;
  pasteHint: string;
  macUpsell: string;
  micDenied: string;
  cleanupFailed: string;
  empty: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    heading: "Dictate",
    intro: "Speak, and WaiComputer cleans it up — then paste it anywhere.",
    start: "Start dictating",
    connecting: "Connecting…",
    listening: "Listening…",
    stop: "Stop",
    cleaning: "Cleaning up…",
    copied: "Copied to clipboard",
    copyAgain: "Copy again",
    again: "New dictation",
    pasteHint: "Press ⌘/Ctrl+V to paste it wherever you like.",
    macUpsell: "For system-wide push-to-talk that types into any app, get the Mac app.",
    micDenied: "Microphone access is required to dictate.",
    cleanupFailed: "AI cleanup was unavailable — copied the raw transcript instead.",
    empty: "Didn't catch anything — try again.",
  },
  ru: {
    heading: "Диктовка",
    intro: "Говорите — WaiComputer причешет текст, потом вставьте куда угодно.",
    start: "Начать диктовку",
    connecting: "Подключение…",
    listening: "Слушаю…",
    stop: "Стоп",
    cleaning: "Обработка…",
    copied: "Скопировано в буфер",
    copyAgain: "Скопировать снова",
    again: "Новая диктовка",
    pasteHint: "Нажмите ⌘/Ctrl+V, чтобы вставить.",
    macUpsell: "Для системной диктовки в любое приложение — установите приложение для Mac.",
    micDenied: "Для диктовки нужен доступ к микрофону.",
    cleanupFailed: "ИИ-обработка недоступна — скопирован исходный текст.",
    empty: "Ничего не распознал — попробуйте ещё раз.",
  },
};

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Apply the custom dictionary: REPLACE entries (word → replacement) substitute
 *  whole words case-insensitively; BIAS entries (no replacement) are returned
 *  as vocabulary to preserve through AI cleanup. */
export function applyDictionary(
  text: string,
  words: DictationDictionaryWord[],
): { text: string; vocabulary: string[] } {
  let out = text;
  const vocabulary: string[] = [];
  for (const entry of words) {
    if (entry.replacement) {
      out = out.replace(new RegExp(`\\b${escapeRegExp(entry.word)}\\b`, "gi"), entry.replacement);
      vocabulary.push(entry.replacement);
    } else {
      vocabulary.push(entry.word);
    }
  }
  return { text: out, vocabulary };
}

function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

interface DictatePanelProps {
  locale?: Locale;
}

export function DictatePanel({ locale = "en" }: DictatePanelProps) {
  const copy = COPY[locale];
  const [state, setState] = useState<RealtimeState>("idle");
  const [phase, setPhase] = useState<"record" | "cleaning" | "ready">("record");
  const [seconds, setSeconds] = useState(0);
  const [committed, setCommitted] = useState("");
  const [interim, setInterim] = useState("");
  const [result, setResult] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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
    setError(null);
    setNotice(null);
    setResult("");
    setCommitted("");
    setInterim("");
    setSeconds(0);
    setPhase("record");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError(copy.micDenied);
      return;
    }
    const transcriber = new RealtimeTranscriber({
      purpose: "dictation",
      onState: setState,
      onUpdate: ({ committed: c, interim: i }) => {
        setCommitted(c);
        setInterim(i);
      },
      onError: (message) => {
        clearTimer();
        setError(message);
      },
    });
    transcriberRef.current = transcriber;
    await transcriber.start(stream);
    if (transcriber.getState() === "recording") {
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    }
  }, [clearTimer, copy.micDenied]);

  const copyText = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return false;
    }
  }, []);

  const stop = useCallback(async () => {
    clearTimer();
    const transcriber = transcriberRef.current;
    if (!transcriber) return;
    const elapsed = seconds;
    const segments = await transcriber.stop();
    transcriberRef.current = null;
    const raw = segments
      .map((s) => s.text)
      .join(" ")
      .trim();
    if (!raw) {
      setState("idle");
      setNotice(copy.empty);
      return;
    }

    setPhase("cleaning");
    let words: DictationDictionaryWord[] = [];
    try {
      words = await listDictionaryWords();
    } catch {
      // Dictionary is best-effort; cleanup still runs without it.
    }
    const { text: replaced, vocabulary } = applyDictionary(raw, words);

    let cleaned = replaced;
    try {
      cleaned = (await cleanupDictation(replaced, vocabulary)).text || replaced;
    } catch {
      // Explicit recovery path: keep the (dictionary-applied) raw transcript so
      // the user always has something to paste, and tell them cleanup was off.
      setNotice(copy.cleanupFailed);
    }

    setResult(cleaned);
    setPhase("ready");
    setState("idle");
    await copyText(cleaned);

    // Log to the unified dictation history/quota (best-effort).
    try {
      await createDictationEntry({
        client_entry_id: crypto.randomUUID(),
        raw_text: raw,
        cleaned_text: cleaned,
        duration_seconds: elapsed,
        word_count: countWords(cleaned),
        occurred_at: new Date().toISOString(),
      });
    } catch {
      // history logging failure shouldn't block the paste flow
    }
  }, [clearTimer, copy.cleanupFailed, copy.empty, copyText, seconds]);

  const reset = useCallback(() => {
    setPhase("record");
    setResult("");
    setCommitted("");
    setInterim("");
    setNotice(null);
    setError(null);
    setSeconds(0);
  }, []);

  const isRecording = state === "connecting" || state === "recording" || state === "stopping";

  return (
    <section className="tool-panel dictate-panel" data-testid="dictate-panel">
      <header className="panel-header">
        <div>
          <h3>{copy.heading}</h3>
          <p className="muted-text">{copy.intro}</p>
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

      {phase === "ready" ? (
        <div className="dictate-result" data-testid="dictate-result">
          <p className="dictate-result__text">{result}</p>
          <p className="settings-note">{copy.pasteHint}</p>
          <div className="metadata-row">
            <button
              type="button"
              className="ghost-button compact-button"
              onClick={() => void copyText(result)}
            >
              {copy.copyAgain}
            </button>
            <button type="button" className="ghost-button compact-button" onClick={reset}>
              {copy.again}
            </button>
          </div>
        </div>
      ) : isRecording || phase === "cleaning" ? (
        <div className="live-recorder__active">
          <div className="live-recorder__status">
            {state === "recording" ? (
              <span className="live-recorder__dot" aria-hidden="true" />
            ) : null}
            <span className="mono live-recorder__timer">{`${Math.floor(seconds / 60)}:${(seconds % 60)
              .toString()
              .padStart(2, "0")}`}</span>
            <span className="live-recorder__label">
              {phase === "cleaning"
                ? copy.cleaning
                : state === "connecting"
                  ? copy.connecting
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
      ) : (
        <button type="button" className="dictate-start" onClick={() => void start()}>
          {copy.start}
        </button>
      )}

      <p className="settings-note dictate-upsell">{copy.macUpsell}</p>
    </section>
  );
}
