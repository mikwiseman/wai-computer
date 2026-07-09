"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/http";
import { createDictationBenchmarkBattle, submitDictationBenchmarkVote } from "@/lib/api";
import type { DictationBenchmarkBattleResponse, DictationBenchmarkCandidate } from "@/lib/types";
import styles from "./benchmark.module.css";

type RecorderState = "idle" | "recording" | "uploading" | "done" | "error";
type CandidateStatus = "standby" | "running" | "ok" | "error";
type BattleCandidate = Omit<DictationBenchmarkCandidate, "status"> & { status: CandidateStatus };

type ArenaCopy = {
  eyebrow: string;
  title: string;
  start: string;
  stop: string;
  steps: {
    record: string;
    run: string;
    vote: string;
  };
  statuses: Record<RecorderState, string>;
  signInMessage: string;
  signIn: string;
  modelHidden: string;
  selected: string;
  savingVote: string;
  voteSaved: string;
  pickWinner: string;
  newRound: string;
  recordingHint: string;
  recordingLiveHint: string;
  runningHint: string;
  resultsHint: string;
  privateRound: string;
  sameAudio: string;
  blindVote: string;
  languageLabel: string;
  runningModelsLabel: string;
  outputsReadyLabel: string;
  wordsLabel: string;
  languageOptions: Array<{ label: string; value: string }>;
  micUnavailable: string;
  micPermissionDenied: string;
  emptyRecording: string;
  requestFailed: string;
  voteFailed: string;
  transcribingSameAudio: string;
  waitingForVote: string;
  livePass: string;
  fullPass: string;
  liveWaiting: string;
  liveConnectionFailed: string;
};

type AudioContextConstructor = new () => AudioContext;

const arenaModels = [{ id: "elevenlabs", label: "ElevenLabs", status: "standby" as CandidateStatus }];
const idleWaveLevels = Array.from({ length: 26 }, (_, index) => 0.22 + ((index * 17) % 54) / 100);

const defaultCopy: ArenaCopy = {
  eyebrow: "File STT check",
  title: "Record once, verify full transcription",
  start: "Start recording",
  stop: "Stop and transcribe",
  steps: {
    record: "Record",
    run: "Transcribe",
    vote: "Review",
  },
  statuses: {
    idle: "Ready",
    recording: "Recording",
    uploading: "Transcribing",
    done: "Transcript ready",
    error: "Needs attention",
  },
  signInMessage: "Sign in to run a private transcription check.",
  signIn: "Sign in",
  modelHidden: "Model hidden",
  selected: "Selected",
  savingVote: "Saving",
  voteSaved: "Saved",
  pickWinner: "Confirm",
  newRound: "New round",
  recordingHint: "Speak naturally. Stop when the phrase is complete.",
  recordingLiveHint: "Speak naturally. Stop when the phrase is complete.",
  runningHint: "The same audio is being transcribed by the active file STT model.",
  resultsHint: "Review the transcript before confirming.",
  privateRound: "Private round. Audio is used for this request only.",
  sameAudio: "One audio sample.",
  blindVote: "Single active file STT model.",
  languageLabel: "Language",
  runningModelsLabel: "Active model",
  outputsReadyLabel: "outputs ready",
  wordsLabel: "words",
  languageOptions: [
    { label: "Auto", value: "multi" },
    { label: "English", value: "en" },
    { label: "Russian", value: "ru" },
  ],
  micUnavailable: "Microphone recording is not available in this browser.",
  micPermissionDenied: "Microphone access was blocked. Allow microphone access in the browser, then start a new round.",
  emptyRecording: "No audio was captured. Start a new round and speak for at least a second.",
  requestFailed: "Transcription request failed.",
  voteFailed: "Confirmation was not saved.",
  transcribingSameAudio: "Transcribing the same audio…",
  waitingForVote: "Waiting for review.",
  livePass: "Live pass",
  fullPass: "Full pass",
  liveWaiting: "Waiting for transcript…",
  liveConnectionFailed: "Live benchmark connection failed.",
};

function isPermissionDenied(error: unknown): boolean {
  if (!error || typeof error !== "object") {
    return false;
  }
  const name = "name" in error ? String(error.name).toLowerCase() : "";
  const message = "message" in error ? String(error.message).toLowerCase() : "";
  return (
    name === "notallowederror"
    || name === "securityerror"
    || message.includes("permission denied")
    || message.includes("permission dismissed")
  );
}

function getAudioContextConstructor(): AudioContextConstructor | undefined {
  return window.AudioContext
    ?? (window as typeof window & { webkitAudioContext?: AudioContextConstructor }).webkitAudioContext;
}

export function DictationBenchmarkArena({
  copy = defaultCopy,
  signInHref = "/login",
}: {
  copy?: ArenaCopy;
  signInHref?: string;
}) {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserFrameRef = useRef<number | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [battle, setBattle] = useState<DictationBenchmarkBattleResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [language, setLanguage] = useState("multi");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [savingVoteId, setSavingVoteId] = useState<string | null>(null);
  const [savedVoteId, setSavedVoteId] = useState<string | null>(null);
  const [waveLevels, setWaveLevels] = useState(idleWaveLevels);

  useEffect(() => {
    if (state !== "recording" || startedAt === null) {
      return undefined;
    }
    const interval = window.setInterval(() => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    }, 250);
    return () => window.clearInterval(interval);
  }, [startedAt, state]);

  useEffect(() => {
    return () => {
      stopAudioMeter();
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const elapsedLabel = useMemo(() => {
    const minutes = Math.floor(elapsedSeconds / 60);
    const seconds = `${elapsedSeconds % 60}`.padStart(2, "0");
    return `${minutes}:${seconds}`;
  }, [elapsedSeconds]);

  function stopAudioMeter() {
    if (analyserFrameRef.current !== null) {
      window.cancelAnimationFrame(analyserFrameRef.current);
      analyserFrameRef.current = null;
    }
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    setWaveLevels(idleWaveLevels);
  }

  function startAudioMeter(stream: MediaStream) {
    stopAudioMeter();
    const AudioContextConstructor = getAudioContextConstructor();
    if (!AudioContextConstructor) {
      return;
    }

    try {
      const context = new AudioContextConstructor();
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      context.createMediaStreamSource(stream).connect(analyser);
      audioContextRef.current = context;

      const data = new Uint8Array(analyser.fftSize);
      const bucketCount = idleWaveLevels.length;
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        const bucketSize = Math.floor(data.length / bucketCount);
        const nextLevels = Array.from({ length: bucketCount }, (_, bucketIndex) => {
          let total = 0;
          for (let sampleIndex = 0; sampleIndex < bucketSize; sampleIndex += 1) {
            const value = data[bucketIndex * bucketSize + sampleIndex] - 128;
            total += Math.abs(value);
          }
          const average = total / Math.max(1, bucketSize);
          return Math.min(0.95, Math.max(0.16, 0.18 + average / 44));
        });
        setWaveLevels(nextLevels);
        analyserFrameRef.current = window.requestAnimationFrame(tick);
      };
      tick();
    } catch {
      setWaveLevels(idleWaveLevels);
    }
  }

  async function uploadAudio(audio: File) {
    setState("uploading");
    setError(null);
    setSelectedId(null);
    setSavingVoteId(null);
    setSavedVoteId(null);
    try {
      const result = await createDictationBenchmarkBattle({
        audio,
        filename: audio.name,
        language,
      });
      setBattle(result);
      setSelectedId(null);
      setSavingVoteId(null);
      setSavedVoteId(null);
      setState("done");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError(copy.signInMessage);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError(copy.requestFailed);
      }
      setState("error");
    }
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(copy.micUnavailable);
      setState("error");
      return;
    }

    setBattle(null);
    setError(null);
    setSelectedId(null);
    setSavingVoteId(null);
    setSavedVoteId(null);
    setElapsedSeconds(0);
    chunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      startAudioMeter(stream);
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((candidate) =>
        MediaRecorder.isTypeSupported(candidate),
      );
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const blobType = recorder.mimeType || mimeType || "audio/webm";
        const extension = blobType.includes("mp4") ? "m4a" : "webm";
        const blob = new Blob(chunksRef.current, { type: blobType });
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        stopAudioMeter();
        setStartedAt(null);
        if (blob.size === 0) {
          setError(copy.emptyRecording);
          setState("error");
          return;
        }
        void uploadAudio(new File([blob], `dictation-benchmark.${extension}`, { type: blobType }));
      };
      recorder.start(500);
      setStartedAt(Date.now());
      setState("recording");
    } catch (err) {
      stopAudioMeter();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setError(isPermissionDenied(err) ? copy.micPermissionDenied : copy.micUnavailable);
      setState("error");
    }
  }

  function stopRecording() {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      return;
    }
    recorder.stop();
  }

  async function pickWinner(
    candidate: BattleCandidate | DictationBenchmarkCandidate,
    battleId: string,
    candidateCount: number,
    voteLanguage: string,
  ) {
    if (candidate.status !== "ok") {
      return;
    }
    setSelectedId(candidate.id);
    setSavingVoteId(candidate.id);
    setError(null);
    try {
      await submitDictationBenchmarkVote({
        battle_id: battleId,
        selected_candidate_id: candidate.id,
        selected_provider: candidate.provider,
        selected_model: candidate.model,
        language: voteLanguage,
        candidate_count: candidateCount,
      });
      setSavedVoteId(candidate.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.voteFailed);
    } finally {
      setSavingVoteId(null);
    }
  }

  const revealed = selectedId !== null;
  const showRunningPlaceholders = state === "uploading" && !battle;
  const activeCandidates: BattleCandidate[] = (battle?.candidates as BattleCandidate[] | undefined) ?? [];
  const readyCount = activeCandidates.filter((candidate) => candidate.status === "ok").length;
  const totalCount = activeCandidates.length || battle?.candidates.length || 0;
  const railModels = activeCandidates.length > 0
    ? activeCandidates.map((candidate) => ({
        id: candidate.id,
        label: revealed ? candidate.label : copy.modelHidden,
        status: candidate.status,
      }))
    : arenaModels.map((model) => ({
        ...model,
        status: state === "uploading" ? "running" as CandidateStatus : state === "recording" ? "running" as CandidateStatus : "standby" as CandidateStatus,
      }));
  const hint =
    state === "done"
      ? `${readyCount}/${totalCount} ${copy.outputsReadyLabel}. ${copy.resultsHint}`
      : state === "uploading"
        ? copy.runningHint
        : copy.recordingHint;

  return (
    <section className={styles.arena} id="arena" aria-labelledby="arena-title">
      <div className={styles.arenaHeader}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h2 id="arena-title">{copy.title}</h2>
        </div>
        <div className={styles.arenaStatusBoard} aria-label="Battle status">
          <span data-active={state === "recording"}>{copy.steps.record}</span>
          <span data-active={state === "uploading"}>{copy.steps.run}</span>
          <span data-active={state === "done"}>{copy.steps.vote}</span>
          <strong>{copy.statuses[state]}</strong>
        </div>
      </div>

      <div className={styles.battleConsole}>
        <div className={styles.recorderPanel}>
          <div className={styles.recorderTopline}>
            <span className={styles.liveDot} data-state={state} />
            <span className={styles.timer}>{state === "recording" ? elapsedLabel : "0:00"}</span>
          </div>
          <div className={styles.waveform} aria-hidden="true">
            {waveLevels.map((level, index) => (
              <span
                key={index}
                style={{ animationDelay: `${index * 42}ms`, height: `${Math.round(level * 100)}%` }}
              />
            ))}
          </div>
          <div className={styles.battleStrip} aria-label="Battle mechanics">
            <span>{copy.sameAudio}</span>
            <strong>A</strong>
            <span>{copy.blindVote}</span>
          </div>
          <p className={styles.recorderHint}>{hint}</p>
          <div className={styles.languagePicker} aria-label={copy.languageLabel}>
            <span>{copy.languageLabel}</span>
            <div>
              {copy.languageOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={language === option.value ? styles.languageSelected : styles.languageButton}
                  onClick={() => setLanguage(option.value)}
                  disabled={state === "recording" || state === "uploading"}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className={styles.recorderActions}>
            {state === "recording" ? (
              <button className={styles.primaryButton} type="button" onClick={stopRecording}>
                {copy.stop}
              </button>
            ) : (
              <button
                className={styles.primaryButton}
                type="button"
                onClick={() => void startRecording()}
                disabled={state === "uploading"}
              >
                {battle ? copy.newRound : copy.start}
              </button>
            )}
            <span className={styles.privateRound}>{copy.privateRound}</span>
          </div>
        </div>

        <div className={styles.runningPanel}>
          <span className={styles.panelLabel}>{copy.runningModelsLabel}</span>
          <div className={styles.modelRails}>
            {railModels.map((model, index) => (
              <div className={styles.modelRail} key={model.id}>
                <span>{String.fromCharCode(65 + index)}</span>
                <strong>{model.label}</strong>
                <em data-status={model.status}>{model.status}</em>
              </div>
            ))}
          </div>
        </div>
      </div>

      {error ? (
        <div className={styles.notice}>
          <span>{error}</span>
          {error === copy.signInMessage ? <Link href={signInHref}>{copy.signIn}</Link> : null}
        </div>
      ) : null}

      {showRunningPlaceholders ? (
        <div className={styles.candidateGrid} aria-live="polite">
          {arenaModels.map((model, index) => (
            <article className={`${styles.candidate} ${styles.candidatePending}`} key={model.id}>
              <div className={styles.candidateTop}>
                <span className={styles.candidateLetter}>{String.fromCharCode(65 + index)}</span>
                <span className={styles.candidateMeta}>{copy.modelHidden}</span>
              </div>
              <p className={styles.transcriptText}>{copy.transcribingSameAudio}</p>
              <div className={styles.candidateFooter}>
                <span>{copy.waitingForVote}</span>
                <button type="button" className={styles.voteButton} disabled>
                  {copy.pickWinner}
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {activeCandidates.length > 0 ? (
        <div className={styles.candidateGrid}>
          {activeCandidates.map((candidate, index) => (
            <article className={styles.candidate} key={candidate.id}>
              <div className={styles.candidateTop}>
                <span className={styles.candidateLetter}>{String.fromCharCode(65 + index)}</span>
                <span className={styles.candidateMeta}>
                  {revealed ? candidate.label : copy.modelHidden}
                </span>
              </div>
              <p className={styles.transcriptText}>
                {candidate.status === "error"
                  ? candidate.error
                  : candidate.transcript || copy.liveWaiting}
              </p>
              <div className={styles.candidateFooter}>
                <span>
                  {candidate.latency_ms ?? "-"} ms · {candidate.word_count ?? "-"} {copy.wordsLabel}
                </span>
                <button
                  type="button"
                  className={selectedId === candidate.id ? styles.voteSelected : styles.voteButton}
                  disabled={candidate.status !== "ok"}
                  onClick={() => {
                    if (battle) {
                      void pickWinner(candidate, battle.battle_id, activeCandidates.length, battle.language);
                    }
                  }}
                >
                  {savingVoteId === candidate.id
                    ? copy.savingVote
                    : savedVoteId === candidate.id
                      ? copy.voteSaved
                      : selectedId === candidate.id
                        ? copy.selected
                        : copy.pickWinner}
                </button>
              </div>
              {revealed ? (
                <div className={styles.reveal}>
                  {candidate.provider} / {candidate.model}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
