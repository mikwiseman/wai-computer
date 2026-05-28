"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";

import { enrollVoice } from "@/lib/api";
import { normalizeAuthLocale, type AuthLocale } from "@/lib/auth-locale";

type Locale = AuthLocale;

const MAX_DURATION_S = 20;
const STORAGE_KEY = "voice_onboarding_complete";

const COPY: Record<
  Locale,
  {
    step: string;
    heading: string;
    lead: string;
    prompt: string;
    record: string;
    stop: string;
    use: string;
    rerecord: string;
    skip: string;
    uploading: string;
    privacy: string;
    statusIdle: string;
    statusRecording: (elapsed: number) => string;
    statusRecorded: (elapsed: number) => string;
    statusUploading: string;
    micError: string;
    uploadError: string;
  }
> = {
  en: {
    step: "Step 1 of 1",
    heading: "Teach Wai your voice",
    lead: "Read the prompt for ~20 seconds. Wai will recognise you in future meetings automatically.",
    prompt:
      "Hi, I'm setting up WaiComputer. It records meetings, calls, and ideas through my day so I don't have to remember them all. Wai listens, transcribes the people I talk to, and keeps the moments that matter.",
    record: "Record",
    stop: "Stop",
    use: "Use this take",
    rerecord: "Re-record",
    skip: "Skip for now",
    uploading: "Uploading voice signature…",
    privacy:
      "We store a 192-number signature, not your audio. The recording is deleted after the signature is created.",
    statusIdle: "Press the mic to start",
    statusRecording: (elapsed) => `Recording… ${Math.floor(elapsed)}s / ${MAX_DURATION_S}s`,
    statusRecorded: (elapsed) => `Recorded ${Math.floor(elapsed)}s. Use it or re-record.`,
    statusUploading: "Uploading voice signature…",
    micError: "Could not start microphone",
    uploadError: "Upload failed",
  },
  ru: {
    step: "Шаг 1 из 1",
    heading: "Научите Wai вашему голосу",
    lead: "Прочитайте текст примерно за 20 секунд. Wai будет узнавать вас на будущих встречах автоматически.",
    prompt:
      "Привет, я настраиваю WaiComputer. Он записывает встречи, звонки и идеи в течение дня, чтобы мне не приходилось всё держать в голове. Wai слушает, расшифровывает речь собеседников и сохраняет важные моменты.",
    record: "Записать",
    stop: "Остановить",
    use: "Использовать запись",
    rerecord: "Перезаписать",
    skip: "Пропустить",
    uploading: "Загружаем голосовой профиль…",
    privacy:
      "Мы храним профиль из 192 чисел, а не вашу аудиозапись. Сама запись удаляется сразу после создания профиля.",
    statusIdle: "Нажмите микрофон, чтобы начать",
    statusRecording: (elapsed) => `Запись… ${Math.floor(elapsed)}с / ${MAX_DURATION_S}с`,
    statusRecorded: (elapsed) => `Записано ${Math.floor(elapsed)}с. Используйте или перезапишите.`,
    statusUploading: "Загружаем голосовой профиль…",
    micError: "Не удалось получить доступ к микрофону",
    uploadError: "Не удалось загрузить запись",
  },
};

type RecorderState = "idle" | "recording" | "recorded" | "uploading";

function detectLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  const candidates = [
    ...Array.from(navigator.languages ?? []),
    navigator.language,
  ].filter(Boolean);
  return normalizeAuthLocale(candidates[0]);
}

function subscribeToLanguage(callback: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("languagechange", callback);
  return () => window.removeEventListener("languagechange", callback);
}

function useBrowserLocale(initialLocale?: Locale): Locale {
  const fallback = initialLocale ?? "en";
  const detected = useSyncExternalStore(
    subscribeToLanguage,
    () => detectLocale(),
    () => fallback,
  );
  return initialLocale ?? detected;
}

interface OnboardingClientProps {
  initialLocale?: Locale;
}

export function OnboardingClient({ initialLocale }: OnboardingClientProps) {
  const router = useRouter();
  const locale = useBrowserLocale(initialLocale);
  const [state, setState] = useState<RecorderState>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const startedAtRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const copy = COPY[locale];

  useEffect(() => {
    markOnboardingSeen();

    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  function stopStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  function pickMimeType(): { mimeType: string; filename: string } {
    if (typeof MediaRecorder !== "undefined") {
      if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
        return { mimeType: "audio/webm;codecs=opus", filename: "enrollment.webm" };
      }
      if (MediaRecorder.isTypeSupported("audio/mp4")) {
        return { mimeType: "audio/mp4", filename: "enrollment.m4a" };
      }
      if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) {
        return { mimeType: "audio/ogg;codecs=opus", filename: "enrollment.ogg" };
      }
    }
    return { mimeType: "audio/webm", filename: "enrollment.webm" };
  }

  async function startRecording() {
    setError(null);
    setAudioBlob(null);
    chunksRef.current = [];
    setElapsed(0);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const { mimeType } = pickMimeType();
      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeType });
        setAudioBlob(blob);
        setState("recorded");
        stopStream();
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
      };

      recorder.start();
      startedAtRef.current = Date.now();
      setState("recording");

      timerRef.current = setInterval(() => {
        const seconds = (Date.now() - startedAtRef.current) / 1000;
        setElapsed(seconds);
        if (seconds >= MAX_DURATION_S) {
          recorder.stop();
        }
      }, 100);
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.micError);
      stopStream();
      setState("idle");
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
  }

  async function submit() {
    if (!audioBlob) return;
    setState("uploading");
    setError(null);
    try {
      const { filename } = pickMimeType();
      await enrollVoice({ audio: audioBlob, filename });
      markOnboardingSeen();
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.uploadError);
      setState("recorded");
    }
  }

  function skip() {
    markOnboardingSeen();
    router.replace("/dashboard");
  }

  function reset() {
    setAudioBlob(null);
    setElapsed(0);
    setState("idle");
    setError(null);
  }

  const progress = Math.min((elapsed / MAX_DURATION_S) * 100, 100);
  const isRecording = state === "recording";

  return (
    <div className="onboarding-shell">
      <p className="onboarding-step">{copy.step}</p>
      <h1>{copy.heading}</h1>
      <p className="onboarding-lead">{copy.lead}</p>

      <article className="onboarding-prompt-card">
        <p>{copy.prompt}</p>
      </article>

      <div className="onboarding-controls">
        <button
          type="button"
          className={`onboarding-record-button ${isRecording ? "onboarding-record-button--recording" : ""}`}
          onClick={isRecording ? stopRecording : startRecording}
          disabled={state === "uploading"}
        >
          {isRecording ? copy.stop : copy.record}
        </button>

        <div className="onboarding-progress-stack">
          <div className="onboarding-progress-bar">
            <div
              className="onboarding-progress-fill"
              style={{ width: `${progress}%` }}
              aria-hidden="true"
            />
          </div>
          <p className="onboarding-status">{statusLabel(copy, state, elapsed)}</p>
          {error ? <p className="onboarding-error">{error}</p> : null}
        </div>
      </div>

      {state === "recorded" ? (
        <div className="onboarding-take-actions">
          <button type="button" className="primary" onClick={submit}>
            {copy.use}
          </button>
          <button type="button" className="ghost" onClick={reset}>
            {copy.rerecord}
          </button>
        </div>
      ) : null}

      {state === "uploading" ? (
        <p className="onboarding-status">{copy.statusUploading}</p>
      ) : null}

      <button type="button" className="ghost-button onboarding-skip" onClick={skip}>
        {copy.skip}
      </button>

      <p className="onboarding-privacy">{copy.privacy}</p>
    </div>
  );
}

function markOnboardingSeen() {
  window.localStorage.setItem(STORAGE_KEY, "true");
}

function statusLabel(
  copy: (typeof COPY)[Locale],
  state: RecorderState,
  elapsed: number,
): string {
  switch (state) {
    case "idle":
      return copy.statusIdle;
    case "recording":
      return copy.statusRecording(elapsed);
    case "recorded":
      return copy.statusRecorded(elapsed);
    case "uploading":
      return copy.statusUploading;
  }
}
