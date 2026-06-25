"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createDictationEntry,
  listDictionaryWords,
} from "@/lib/api";
import { RealtimeTranscriber, type RealtimeState } from "@/lib/realtime";
import type {
  DictationDictionaryWord,
  RealtimeTranscriptionReplacement,
  TranscriptSegmentInput,
} from "@/lib/types";

type Locale = "en" | "ru";
type DictionaryRealtimeHints = ReturnType<typeof dictionaryRealtimeHints>;

interface Copy {
  heading: string;
  intro: string;
  start: string;
  connecting: string;
  listening: string;
  stop: string;
  preparing: string;
  copied: string;
  copyAgain: string;
  again: string;
  pasteHint: string;
  macUpsell: string;
  micDenied: string;
  dictionaryFailed: string;
  historyFailed: string;
  empty: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    heading: "Dictate",
    intro: "Speak, then paste the transcript anywhere.",
    start: "Start dictating",
    connecting: "Connecting…",
    listening: "Listening…",
    stop: "Stop",
    preparing: "Preparing text…",
    copied: "Copied to clipboard",
    copyAgain: "Copy again",
    again: "New dictation",
    pasteHint: "Press ⌘/Ctrl+V to paste it wherever you like.",
    macUpsell: "For system-wide push-to-talk that types into any app, get the Mac app.",
    micDenied: "Microphone access is required to dictate.",
    dictionaryFailed: "Dictionary could not load — copied transcript without custom replacements.",
    historyFailed: "Copied transcript, but dictation history could not be saved.",
    empty: "Didn't catch anything — try again.",
  },
  ru: {
    heading: "Диктовка",
    intro: "Говорите, затем вставьте расшифровку куда угодно.",
    start: "Начать диктовку",
    connecting: "Подключение…",
    listening: "Слушаю…",
    stop: "Стоп",
    preparing: "Готовим текст…",
    copied: "Скопировано в буфер",
    copyAgain: "Скопировать снова",
    again: "Новая диктовка",
    pasteHint: "Нажмите ⌘/Ctrl+V, чтобы вставить.",
    macUpsell: "Для системной диктовки в любое приложение — установите приложение для Mac.",
    micDenied: "Для диктовки нужен доступ к микрофону.",
    dictionaryFailed: "Не удалось загрузить словарь — скопирована расшифровка без ваших замен.",
    historyFailed: "Расшифровка скопирована, но история диктовки не сохранилась.",
    empty: "Ничего не распознал — попробуйте ещё раз.",
  },
};

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Apply the custom dictionary: REPLACE entries (word → replacement) substitute
 *  whole words case-insensitively; BIAS entries are carried by native clients
 *  as Deepgram keyterm hints before recognition. */
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

export function dictionaryRealtimeHints(words: DictationDictionaryWord[]): {
  keyterms: string[];
  replacements: RealtimeTranscriptionReplacement[];
} {
  const keyterms: string[] = [];
  const keytermSet = new Set<string>();
  const replacements: RealtimeTranscriptionReplacement[] = [];

  function addKeyterm(value: string): void {
    const clean = value.trim();
    if (!clean) return;
    const key = clean.toLocaleLowerCase();
    if (keytermSet.has(key)) return;
    keytermSet.add(key);
    keyterms.push(clean);
  }

  for (const entry of words) {
    if (entry.replacement) {
      addKeyterm(entry.replacement);
      replacements.push({ find: entry.word, replace: entry.replacement });
    } else {
      addKeyterm(entry.word);
    }
  }

  return { keyterms, replacements };
}

function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function stopMediaStream(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}

function reportRealtimeCleanupError(error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  if (typeof console !== "undefined") {
    console.warn("Realtime transcription cleanup failed:", message);
  }
}

interface DictatePanelProps {
  locale?: Locale;
}

export function DictatePanel({ locale = "en" }: DictatePanelProps) {
  const copy = COPY[locale];
  const [state, setState] = useState<RealtimeState>("idle");
  const [phase, setPhase] = useState<"record" | "preparing" | "ready">("record");
  const [seconds, setSeconds] = useState(0);
  const [committed, setCommitted] = useState("");
  const [interim, setInterim] = useState("");
  const [result, setResult] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const transcriberRef = useRef<RealtimeTranscriber | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);
  const dictionaryHintsRef = useRef<DictionaryRealtimeHints>({
    keyterms: [],
    replacements: [],
  });
  const dictionaryLoadRef = useRef<Promise<DictationDictionaryWord[]> | null>(null);

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

  const loadDictionaryWords = useCallback(() => {
    if (dictionaryLoadRef.current) return dictionaryLoadRef.current;
    dictionaryLoadRef.current = listDictionaryWords()
      .then((words) => {
        dictionaryHintsRef.current = dictionaryRealtimeHints(words);
        return words;
      })
      .catch((error: unknown) => {
        dictionaryLoadRef.current = null;
        throw error;
      });
    return dictionaryLoadRef.current;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void loadDictionaryWords().catch(() => {
      // The start/stop paths surface dictionary failures when they affect output.
    });
    return () => {
      mountedRef.current = false;
      teardownTranscriber();
    };
  }, [loadDictionaryWords, teardownTranscriber]);

  const start = useCallback(async () => {
    const dictionaryLoad = loadDictionaryWords();
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
    if (!mountedRef.current) {
      stopMediaStream(stream);
      return;
    }
    try {
      await dictionaryLoad;
    } catch {
      setNotice(copy.dictionaryFailed);
    }
    if (!mountedRef.current) {
      stopMediaStream(stream);
      return;
    }
    const transcriber = new RealtimeTranscriber({
      purpose: "dictation",
      keyterms: dictionaryHintsRef.current.keyterms,
      replacements: dictionaryHintsRef.current.replacements,
      onState: (nextState) => {
        if (mountedRef.current) setState(nextState);
      },
      onUpdate: ({ committed: c, interim: i }) => {
        if (!mountedRef.current) return;
        setCommitted(c);
        setInterim(i);
      },
      onError: (message) => {
        if (!mountedRef.current) return;
        clearTimer();
        setError(message);
      },
    });
    transcriberRef.current = transcriber;
    await transcriber.start(stream);
    if (
      mountedRef.current &&
      transcriberRef.current === transcriber &&
      transcriber.getState() === "recording"
    ) {
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    }
  }, [clearTimer, copy.dictionaryFailed, copy.micDenied, loadDictionaryWords]);

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
    transcriberRef.current = null;
    const elapsed = seconds;
    let segments: TranscriptSegmentInput[];
    try {
      segments = await transcriber.stop();
    } catch (error) {
      setPhase("record");
      setState("idle");
      setError(error instanceof Error ? error.message : "Realtime transcription error");
      return;
    }
    const raw = segments
      .map((s) => s.text)
      .join(" ")
      .trim();
    if (!raw) {
      setState("idle");
      setNotice(copy.empty);
      return;
    }

    setPhase("preparing");
    let words: DictationDictionaryWord[] = [];
    try {
      words = await listDictionaryWords();
      dictionaryHintsRef.current = dictionaryRealtimeHints(words);
      dictionaryLoadRef.current = Promise.resolve(words);
    } catch {
      setNotice(copy.dictionaryFailed);
    }
    const { text: replaced } = applyDictionary(raw, words);

    setResult(replaced);
    setPhase("ready");
    setState("idle");
    await copyText(replaced);

    // Keep the paste flow available, but do not hide a history/quota sync failure.
    try {
      await createDictationEntry({
        client_entry_id: crypto.randomUUID(),
        raw_text: raw,
        cleaned_text: replaced,
        duration_seconds: elapsed,
        word_count: countWords(replaced),
        occurred_at: new Date().toISOString(),
      });
    } catch {
      setNotice(copy.historyFailed);
    }
  }, [
    clearTimer,
    copy.dictionaryFailed,
    copy.empty,
    copy.historyFailed,
    copyText,
    seconds,
  ]);

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
      ) : isRecording || phase === "preparing" ? (
        <div className="live-recorder__active">
          <div className="live-recorder__status">
            {state === "recording" ? (
              <span className="live-recorder__dot" aria-hidden="true" />
            ) : null}
            <span className="mono live-recorder__timer">{`${Math.floor(seconds / 60)}:${(seconds % 60)
              .toString()
              .padStart(2, "0")}`}</span>
            <span className="live-recorder__label">
              {phase === "preparing"
                ? copy.preparing
                : state === "connecting"
                  ? copy.connecting
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
