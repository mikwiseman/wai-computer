"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ApiError, getApiBaseUrl } from "@/lib/http";
import { createDictationBenchmarkBattle, submitDictationBenchmarkVote } from "@/lib/api";
import type { DictationBenchmarkBattleResponse, DictationBenchmarkCandidate } from "@/lib/types";
import styles from "./benchmark.module.css";

type RecorderState = "idle" | "recording" | "uploading" | "done" | "error";
type ResultMode = "live" | "full";
type CandidateStatus = "standby" | "listening" | "running" | "ok" | "error";
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

type RailStatus = CandidateStatus;

type RailModel = {
  id: string;
  label: string;
  status: RailStatus;
};

const arenaModels: RailModel[] = [
  { id: "elevenlabs", label: "ElevenLabs", status: "standby" },
  { id: "soniox", label: "Soniox", status: "standby" },
  { id: "deepgram", label: "Deepgram", status: "standby" },
];

const idleWaveLevels = Array.from({ length: 26 }, (_, index) => 0.22 + ((index * 17) % 54) / 100);

const defaultCopy: ArenaCopy = {
  eyebrow: "Live arena",
  title: "Dictate once, compare blind outputs",
  start: "Start dictation battle",
  stop: "Stop and compare",
  steps: {
    record: "Record",
    run: "Run",
    vote: "Vote",
  },
  statuses: {
    idle: "Ready",
    recording: "Recording",
    uploading: "Running models",
    done: "Choose the best transcript",
    error: "Needs attention",
  },
  signInMessage: "Sign in to run a private live benchmark.",
  signIn: "Sign in",
  modelHidden: "Model hidden",
  selected: "Selected",
  savingVote: "Saving",
  voteSaved: "Vote saved",
  pickWinner: "Pick winner",
  newRound: "New round",
  recordingHint: "Speak naturally. Stop when the phrase is complete.",
  recordingLiveHint: "Recording live. Speak naturally, then stop to run every model on the same audio.",
  runningHint: "Same audio is now racing through the models.",
  resultsHint: "Names stay hidden until you pick a winner.",
  privateRound: "Private round. Audio is used for this request only.",
  sameAudio: "One audio sample, all models.",
  blindVote: "Blind vote before reveal.",
  languageLabel: "Language",
  runningModelsLabel: "Running models",
  outputsReadyLabel: "outputs ready",
  wordsLabel: "words",
  languageOptions: [
    { label: "Auto", value: "multi" },
    { label: "English", value: "en" },
    { label: "Russian", value: "ru" },
  ],
  micUnavailable: "Microphone recording is not available in this browser.",
  micPermissionDenied: "Microphone access was blocked. Allow microphone access in the browser, then start a new battle.",
  emptyRecording: "No audio was captured. Start a new battle and speak for at least a second.",
  requestFailed: "Benchmark request failed.",
  voteFailed: "Vote was not saved.",
  transcribingSameAudio: "Transcribing the same audio...",
  waitingForVote: "Waiting for your blind vote.",
  livePass: "Live pass",
  fullPass: "Full pass",
  liveWaiting: "Listening for live transcript...",
  liveConnectionFailed: "Live benchmark connection failed.",
};

type LiveBattleEvent =
  | {
      type: "battle_started";
      battle_id: string;
      language: string;
      candidates: BattleCandidate[];
    }
  | {
      type: "candidate_status" | "candidate_update" | "candidate_error";
      battle_id: string;
      candidate: BattleCandidate;
      is_final?: boolean;
    }
  | {
      type: "battle_finished";
      battle_id: string;
    }
  | {
      type: "battle_error";
      message: string;
    };

type AudioContextConstructor = new () => AudioContext;

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

function buildLiveBattleWebSocketUrl(language: string): string {
  const apiBase = getApiBaseUrl();
  const url = new URL(`${apiBase}/api/benchmarks/dictation/live-battle`, window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("language", language);
  return url.toString();
}

function getAudioContextConstructor(): AudioContextConstructor | undefined {
  return window.AudioContext
    ?? (window as typeof window & { webkitAudioContext?: AudioContextConstructor }).webkitAudioContext;
}

function pcm16FromFloat32(input: Float32Array, sourceSampleRate: number): ArrayBuffer {
  const targetSampleRate = 16_000;
  const ratio = sourceSampleRate / targetSampleRate;
  const outputLength = Math.max(1, Math.floor(input.length / ratio));
  const output = new ArrayBuffer(outputLength * 2);
  const view = new DataView(output);
  for (let index = 0; index < outputLength; index += 1) {
    const sourceIndex = Math.min(input.length - 1, Math.floor(index * ratio));
    const sample = Math.max(-1, Math.min(1, input[sourceIndex] ?? 0));
    view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return output;
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
  const liveAudioContextRef = useRef<AudioContext | null>(null);
  const liveSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const liveProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const liveSocketRef = useRef<WebSocket | null>(null);
  const analyserFrameRef = useRef<number | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [battle, setBattle] = useState<DictationBenchmarkBattleResponse | null>(null);
  const [liveBattleId, setLiveBattleId] = useState<string | null>(null);
  const [liveCandidates, setLiveCandidates] = useState<BattleCandidate[]>([]);
  const [resultMode, setResultMode] = useState<ResultMode>("live");
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
      closeLiveBattleStream();
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
    // Unmount cleanup must run once; refs hold the live audio/socket resources.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  function updateLiveCandidate(candidate: BattleCandidate) {
    setLiveCandidates((current) => {
      const index = current.findIndex((item) => item.id === candidate.id);
      if (index === -1) {
        return [...current, candidate];
      }
      const next = [...current];
      next[index] = {
        ...next[index],
        ...candidate,
        transcript: candidate.transcript ?? next[index].transcript,
      };
      return next;
    });
  }

  function handleLiveBattleEvent(event: LiveBattleEvent) {
    if (event.type === "battle_started") {
      setLiveBattleId(event.battle_id);
      setLiveCandidates(event.candidates);
      setResultMode("live");
      return;
    }
    if (event.type === "candidate_status" || event.type === "candidate_update" || event.type === "candidate_error") {
      updateLiveCandidate(event.candidate);
      return;
    }
    if (event.type === "battle_finished") {
      setLiveCandidates((current) =>
        current.map((candidate) =>
          candidate.status === "running" && candidate.transcript
            ? { ...candidate, status: "ok" }
            : candidate,
        ),
      );
      return;
    }
    if (event.type === "battle_error") {
      setError(event.message);
      setState("error");
    }
  }

  async function startLiveBattleStream(stream: MediaStream) {
    closeLiveBattleStream();
    if (!("WebSocket" in window)) {
      throw new Error(copy.liveConnectionFailed);
    }
    const socket = new WebSocket(buildLiveBattleWebSocketUrl(language));
    socket.binaryType = "arraybuffer";
    liveSocketRef.current = socket;

    socket.onmessage = (message) => {
      if (typeof message.data !== "string") {
        return;
      }
      try {
        handleLiveBattleEvent(JSON.parse(message.data) as LiveBattleEvent);
      } catch {
        setError(copy.liveConnectionFailed);
      }
    };

    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error(copy.liveConnectionFailed)), 5000);
      socket.onopen = () => {
        window.clearTimeout(timeout);
        resolve();
      };
      socket.onerror = () => {
        window.clearTimeout(timeout);
        reject(new Error(copy.liveConnectionFailed));
      };
    });
    socket.onerror = () => {
      setError(copy.liveConnectionFailed);
    };

    const AudioContextConstructor = getAudioContextConstructor();
    if (!AudioContextConstructor) {
      throw new Error(copy.micUnavailable);
    }
    const context = new AudioContextConstructor();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(2048, 1, 1);
    processor.onaudioprocess = (event) => {
      const output = event.outputBuffer.getChannelData(0);
      output.fill(0);
      if (socket.readyState !== WebSocket.OPEN) {
        return;
      }
      socket.send(pcm16FromFloat32(event.inputBuffer.getChannelData(0), context.sampleRate));
    };
    source.connect(processor);
    processor.connect(context.destination);
    liveAudioContextRef.current = context;
    liveSourceRef.current = source;
    liveProcessorRef.current = processor;
  }

  function finishLiveBattleStream() {
    liveProcessorRef.current?.disconnect();
    liveSourceRef.current?.disconnect();
    liveProcessorRef.current = null;
    liveSourceRef.current = null;
    void liveAudioContextRef.current?.close();
    liveAudioContextRef.current = null;
    const socket = liveSocketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "finish" }));
    }
  }

  function closeLiveBattleStream() {
    finishLiveBattleStream();
    const socket = liveSocketRef.current;
    if (socket && socket.readyState !== WebSocket.CLOSED && socket.readyState !== WebSocket.CLOSING) {
      socket.close();
    }
    liveSocketRef.current = null;
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
      setResultMode("full");
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
    setLiveBattleId(null);
    setLiveCandidates([]);
    setResultMode("live");
    setError(null);
    setSelectedId(null);
    setSavingVoteId(null);
    setSavedVoteId(null);
    setElapsedSeconds(0);
    chunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      await startLiveBattleStream(stream);
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
        finishLiveBattleStream();
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
      closeLiveBattleStream();
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
  const showRunningPlaceholders = state === "uploading" && !battle && liveCandidates.length === 0;
  const activeCandidates: BattleCandidate[] =
    resultMode === "live" && liveCandidates.length > 0
      ? liveCandidates
      : (battle?.candidates as BattleCandidate[] | undefined) ?? [];
  const activeBattleId = resultMode === "live" ? liveBattleId : battle?.battle_id;
  const activeLanguage = resultMode === "full" && battle ? battle.language : language;
  const readyCount = activeCandidates.filter((candidate) => candidate.status === "ok").length;
  const totalCount = activeCandidates.length || battle?.candidates.length || 0;
  const railModels: RailModel[] = activeCandidates.length > 0
    ? activeCandidates.map((candidate) => ({
        id: candidate.id,
        label: revealed ? candidate.label : copy.modelHidden,
        status: candidate.status,
      }))
    : battle
    ? battle.candidates.map((candidate) => ({
        id: candidate.id,
        label: revealed ? candidate.label : copy.modelHidden,
        status: candidate.status,
      }))
    : arenaModels.map((model) => ({
        ...model,
        status: state === "uploading" ? "running" : state === "recording" ? "listening" : "standby",
      }));
  const hint =
    state === "done"
      ? `${readyCount}/${totalCount} ${copy.outputsReadyLabel}. ${copy.resultsHint}`
      : state === "uploading"
        ? copy.runningHint
        : state === "recording"
          ? copy.recordingLiveHint
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
            <strong>B</strong>
            <strong>C</strong>
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

      {liveCandidates.length > 0 && battle ? (
        <div className={styles.resultTabs} role="tablist" aria-label="Benchmark result mode">
          <button
            type="button"
            data-active={resultMode === "live"}
            onClick={() => {
              setResultMode("live");
              setSelectedId(null);
              setSavedVoteId(null);
            }}
          >
            {copy.livePass}
          </button>
          <button
            type="button"
            data-active={resultMode === "full"}
            onClick={() => {
              setResultMode("full");
              setSelectedId(null);
              setSavedVoteId(null);
            }}
          >
            {copy.fullPass}
          </button>
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
                  {candidate.latency_ms ?? "—"} ms · {candidate.word_count ?? "—"} {copy.wordsLabel}
                </span>
                <button
                  type="button"
                  className={selectedId === candidate.id ? styles.voteSelected : styles.voteButton}
                  disabled={candidate.status !== "ok"}
                  onClick={() => {
                    if (activeBattleId) {
                      void pickWinner(candidate, activeBattleId, activeCandidates.length, activeLanguage);
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
