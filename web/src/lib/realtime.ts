// Browser realtime transcription client. Streams the mic (and optionally system
// audio) to the SAME proxy the Mac app uses: POST /api/transcription/session →
// open the WS (token via ?token=, since browsers can't set WS headers) → send
// 16 kHz Int16 PCM → render Deepgram interim/final results live → on stop,
// return the collected segments for finalization.

import { createTranscriptionSession } from "@/lib/api";
import { DICTATION_SAMPLE_RATE, TARGET_SAMPLE_RATE, downsamplePcmInt16 } from "@/lib/audio/pcm";
import type {
  RealtimeSessionResponse,
  RealtimeTranscriptionReplacement,
  TranscriptSegmentInput,
} from "@/lib/types";

export interface RealtimeResult {
  transcript: string;
  isFinal: boolean;
  speaker: number | null;
  startMs: number | null;
  endMs: number | null;
}

/** Parse a Deepgram realtime result frame. Pure + unit-tested. */
export function parseRealtimeMessage(raw: string): RealtimeResult | null {
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!payload || typeof payload !== "object") return null;
  const root = payload as Record<string, unknown>;
  const channel = root.channel as { alternatives?: Array<Record<string, unknown>> } | undefined;
  const alternative = channel?.alternatives?.[0];
  if (!alternative || typeof alternative.transcript !== "string") return null;
  const transcript = alternative.transcript.trim();
  if (!transcript) return null;
  const isFinal = root.is_final === true;

  let speaker: number | null = null;
  const words = alternative.words as Array<Record<string, unknown>> | undefined;
  if (Array.isArray(words) && words.length > 0 && typeof words[0].speaker === "number") {
    speaker = words[0].speaker as number;
  }
  const timing = realtimeResultTiming(root, words);
  return { transcript, isFinal, speaker, startMs: timing.startMs, endMs: timing.endMs };
}

export type RealtimeState = "idle" | "connecting" | "recording" | "stopping" | "error";

export interface RealtimeUpdate {
  committed: string;
  interim: string;
}

export interface RealtimeTranscriberOptions {
  language?: string;
  purpose?: "recording" | "dictation";
  keyterms?: string[];
  replacements?: RealtimeTranscriptionReplacement[];
  onUpdate?: (update: RealtimeUpdate) => void;
  onState?: (state: RealtimeState) => void;
  onError?: (message: string) => void;
}

export interface RealtimeSessionRequest {
  language?: string;
  purpose: "recording" | "dictation";
  keyterms?: string[];
  replacements?: RealtimeTranscriptionReplacement[];
}

export interface PrefetchedRealtimeSession {
  request: RealtimeSessionRequest;
  session: RealtimeSessionResponse;
}

export interface RealtimeStartOptions {
  prefetchedSession?: PrefetchedRealtimeSession | null;
}

const STOP_CLOSE_TIMEOUT_MS = 5000;
const DEFAULT_KEEP_ALIVE_INTERVAL_SECONDS = 4;
const FINAL_REPLACEMENT_START_TOLERANCE_MS = 20;
const STARTUP_AUDIO_BUFFER_MAX_BYTES = 1_048_576;
const REALTIME_DRAIN_POLL_INTERVAL_MS = 50;
const REALTIME_DRAIN_MINIMUM_WAIT_MS = 650;
const REALTIME_DRAIN_NO_TRANSCRIPT_WAIT_MS = 2500;
const REALTIME_DRAIN_QUIET_WINDOW_MS = 900;

function realtimeResultTiming(
  root: Record<string, unknown>,
  words: Array<Record<string, unknown>> | undefined,
): { startMs: number | null; endMs: number | null } {
  const rootStart = numberOrNull(root.start);
  const rootDuration = numberOrNull(root.duration);
  if (rootStart != null && rootDuration != null) {
    const startMs = secondsToMs(rootStart);
    return {
      startMs,
      endMs: startMs + secondsToMs(rootDuration),
    };
  }

  if (Array.isArray(words) && words.length > 0) {
    const firstStart = numberOrNull(words[0]?.start);
    const lastEnd = numberOrNull(words[words.length - 1]?.end);
    return {
      startMs: firstStart == null ? null : secondsToMs(firstStart),
      endMs: lastEnd == null ? null : secondsToMs(lastEnd),
    };
  }

  return { startMs: null, endMs: null };
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function secondsToMs(value: number): number {
  return Math.round(value * 1000);
}

function normalizedTokens(value: string): string[] {
  return Array.from(value.matchAll(/[\p{L}\p{N}]+/gu), (match) => match[0].toLowerCase());
}

function isStrictTokenPrefix(prefix: string, value: string): boolean {
  const prefixTokens = normalizedTokens(prefix);
  const valueTokens = normalizedTokens(value);
  return (
    prefixTokens.length > 0 &&
    valueTokens.length > prefixTokens.length &&
    prefixTokens.every((token, index) => token === valueTokens[index])
  );
}

function sameFinalRange(
  previous: TranscriptSegmentInput,
  next: TranscriptSegmentInput,
): boolean {
  const sameStart =
    Math.abs(previous.start_ms - next.start_ms) <= FINAL_REPLACEMENT_START_TOLERANCE_MS;
  const overlaps = next.start_ms < previous.end_ms && next.end_ms > previous.start_ms;
  return sameStart || overlaps;
}

function shouldReplacePreviousFinal(
  previous: TranscriptSegmentInput | undefined,
  next: TranscriptSegmentInput,
  hasProviderTiming: boolean,
): previous is TranscriptSegmentInput {
  if (!previous || !hasProviderTiming) return false;
  if (!sameFinalRange(previous, next)) return false;
  return isStrictTokenPrefix(previous.text, next.text);
}

function shouldDropDuplicateFinal(
  previous: TranscriptSegmentInput | undefined,
  next: TranscriptSegmentInput,
  hasProviderTiming: boolean,
): boolean {
  if (!previous || !hasProviderTiming) return false;
  if (!sameFinalRange(previous, next)) return false;
  return previous.text.trim().toLowerCase() === next.text.trim().toLowerCase();
}

export function realtimeSessionRequestKey(request: RealtimeSessionRequest): string {
  return JSON.stringify({
    language: request.language ?? "multi",
    purpose: request.purpose,
    keyterms: normalizeKeyterms(request.keyterms),
    replacements: normalizeReplacements(request.replacements),
  });
}

function normalizeKeyterms(values: string[] | undefined): string[] {
  return (values ?? []).map((value) => value.trim()).filter(Boolean);
}

function normalizeReplacements(
  values: RealtimeTranscriptionReplacement[] | undefined,
): RealtimeTranscriptionReplacement[] {
  return (values ?? [])
    .map((value) => ({
      find: value.find.trim(),
      replace: value.replace.trim(),
    }))
    .filter((value) => value.find && value.replace);
}

export class RealtimeTranscriber {
  private ctx: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private sources: MediaStreamAudioSourceNode[] = [];
  private ws: WebSocket | null = null;
  private keepAlive: ReturnType<typeof setInterval> | null = null;
  private streams: MediaStream[] = [];
  private state: RealtimeState = "idle";
  private startedAt = 0;
  private lastFinalMs = 0;
  private committedText = "";
  private interimText = "";
  private readonly pendingAudio: ArrayBufferLike[] = [];
  private pendingAudioBytes = 0;
  private stopRequested = false;
  private didSendFinalize = false;
  private finalizationMarkerReceived = false;
  private lastRealtimeEventAt: number | null = null;
  private readonly segments: TranscriptSegmentInput[] = [];
  private readonly opts: RealtimeTranscriberOptions;

  constructor(opts: RealtimeTranscriberOptions = {}) {
    this.opts = opts;
  }

  getState(): RealtimeState {
    return this.state;
  }

  getSegments(): TranscriptSegmentInput[] {
    return this.segments;
  }

  private isConnecting(): boolean {
    return this.state === "connecting";
  }

  private setState(state: RealtimeState): void {
    this.state = state;
    this.opts.onState?.(state);
  }

  async start(input: MediaStream | MediaStream[], options: RealtimeStartOptions = {}): Promise<void> {
    if (this.state !== "idle") return;
    this.stopRequested = false;
    this.didSendFinalize = false;
    this.finalizationMarkerReceived = false;
    this.lastRealtimeEventAt = null;
    this.streams = Array.isArray(input) ? input : [input];
    this.setState("connecting");
    try {
      await this.startAudio();
    } catch (error) {
      if (!this.isConnecting()) return;
      this.fail(error);
      return;
    }
    if (!this.isConnecting()) {
      this.cleanupAudio();
      return;
    }
    this.startedAt = Date.now();
    const request = this.sessionRequest();
    let session: RealtimeSessionResponse;
    try {
      session = await this.sessionConfig(request, options.prefetchedSession);
    } catch (error) {
      if (!this.isConnecting()) return;
      this.fail(error);
      return;
    }
    if (!this.isConnecting()) return;
    if (session.sample_rate !== this.targetSampleRate()) {
      this.fail(
        new Error(
          `Realtime session returned unsupported sample_rate=${session.sample_rate}; expected ${this.targetSampleRate()}`,
        ),
      );
      return;
    }
    try {
      await this.openSocket(session);
      if (!this.isConnecting()) return;
      this.setState("recording");
    } catch (error) {
      if (!this.isConnecting()) return;
      this.fail(error);
    }
  }

  /// Audio is captured (and buffered) before the session mint returns, so the
  /// resample target is pinned by purpose — the same client-side contract the
  /// native apps use — and the minted session must match it exactly.
  private targetSampleRate(): number {
    return (this.opts.purpose ?? "recording") === "dictation"
      ? DICTATION_SAMPLE_RATE
      : TARGET_SAMPLE_RATE;
  }

  private sessionRequest(): RealtimeSessionRequest {
    return {
      language: this.opts.language,
      purpose: this.opts.purpose ?? "recording",
      keyterms: this.opts.keyterms,
      replacements: this.opts.replacements,
    };
  }

  private async sessionConfig(
    request: RealtimeSessionRequest,
    prefetchedSession: PrefetchedRealtimeSession | null | undefined,
  ): Promise<RealtimeSessionResponse> {
    if (
      prefetchedSession &&
      realtimeSessionRequestKey(prefetchedSession.request) === realtimeSessionRequestKey(request)
    ) {
      return prefetchedSession.session;
    }
    return createTranscriptionSession(request);
  }

  private socketUrl(session: RealtimeSessionResponse): string {
    let base = session.websocket_url;
    if (!base) {
      const { protocol, host } = window.location;
      base = `${protocol === "https:" ? "wss" : "ws"}://${host}/api/transcription/stream`;
    }
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}token=${encodeURIComponent(session.token)}`;
  }

  private openSocket(session: RealtimeSessionResponse): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.socketUrl(session));
      ws.binaryType = "arraybuffer";
      this.ws = ws;
      ws.onopen = () => {
        if (this.ws !== ws || !this.isConnecting()) {
          try {
            ws.close();
          } catch {
            /* already closing */
          }
          resolve();
          return;
        }
        try {
          // Explicit null from the mint means the provider needs no app-level
          // keepalives (OpenAI realtime); missing field falls back for older
          // backends (Deepgram cadence).
          const keepAliveSeconds =
            session.keep_alive_interval_seconds === null
              ? 0
              : (session.keep_alive_interval_seconds ?? DEFAULT_KEEP_ALIVE_INTERVAL_SECONDS);
          if (keepAliveSeconds > 0) {
            this.keepAlive = setInterval(() => {
              if (ws.readyState === WebSocket.OPEN) {
                this.sendSocketPayload(ws, JSON.stringify({ type: "KeepAlive" }));
              }
            }, keepAliveSeconds * 1000);
          }
          const flushError = this.flushPendingAudio();
          if (flushError) {
            reject(flushError);
            return;
          }
          resolve();
        } catch (error) {
          reject(error);
        }
      };
      ws.onmessage = (event) => this.onMessage(event);
      ws.onerror = () => reject(new Error("Realtime transcription connection failed"));
      ws.onclose = () => {
        if (this.stopRequested) {
          resolve();
          return;
        }
        if (this.state === "connecting") {
          reject(new Error("Realtime transcription connection closed before it was ready"));
          return;
        }
        // A close during active recording is an unexpected drop — surface it
        // rather than silently degrading.
        if (this.state === "recording") {
          this.opts.onError?.("Realtime connection lost");
          this.cleanup();
          this.setState("error");
        }
      };
    });
  }

  private async startAudio(): Promise<void> {
    const ctx = new AudioContext();
    this.ctx = ctx;
    await ctx.audioWorklet.addModule("/realtime-pcm-worklet.js");
    if (!this.isConnecting()) {
      if (ctx.state !== "closed") void ctx.close();
      return;
    }
    const node = new AudioWorkletNode(ctx, "realtime-pcm-recorder");
    this.node = node;
    node.port.onmessage = (event) => {
      const float = event.data as Float32Array;
      const int16 = downsamplePcmInt16(float, ctx.sampleRate, this.targetSampleRate());
      this.sendOrBufferAudio(int16.buffer);
    };
    // Connect every input stream (mic + optional system audio) to the worklet;
    // the Web Audio graph sums them into one combined PCM stream. NOT connected
    // to ctx.destination — monitoring would echo.
    for (const stream of this.streams) {
      const source = ctx.createMediaStreamSource(stream);
      source.connect(node);
      this.sources.push(source);
    }
  }

  private sendOrBufferAudio(payload: ArrayBufferLike): void {
    const ws = this.ws;
    if (ws && ws.readyState === WebSocket.OPEN) {
      if (this.flushPendingAudio()) return;
      this.sendSocketPayload(ws, payload);
      return;
    }
    if (this.state !== "connecting") return;
    this.pendingAudio.push(payload);
    this.pendingAudioBytes += payload.byteLength;
    if (this.pendingAudioBytes > STARTUP_AUDIO_BUFFER_MAX_BYTES) {
      this.fail(new Error("Realtime transcription connection took too long."));
    }
  }

  private flushPendingAudio(): Error | null {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN || this.pendingAudio.length === 0) return null;
    for (const payload of this.pendingAudio) {
      const error = this.sendSocketPayload(ws, payload);
      if (error) return error;
    }
    this.clearPendingAudio();
    return null;
  }

  private sendSocketPayload(ws: WebSocket, payload: string | ArrayBufferLike): Error | null {
    try {
      ws.send(payload);
      return null;
    } catch (error) {
      const normalized =
        error instanceof Error ? error : new Error("Realtime transcription send failed.");
      this.fail(normalized);
      return normalized;
    }
  }

  private clearPendingAudio(): void {
    this.pendingAudio.length = 0;
    this.pendingAudioBytes = 0;
  }

  private onMessage(event: MessageEvent): void {
    if (typeof event.data !== "string") return;
    const root = parseRealtimeRoot(event.data);
    const result = parseRealtimeMessage(event.data);
    this.recordRealtimeActivity(root, result);
    if (!result) return;
    if (result.isFinal) {
      const hasProviderTiming = result.startMs != null || result.endMs != null;
      const fallbackEndMs = Date.now() - this.startedAt;
      const startMs = result.startMs ?? this.lastFinalMs;
      const endMs = result.endMs ?? fallbackEndMs;
      const segment = {
        text: result.transcript,
        speaker: result.speaker != null ? `Speaker ${result.speaker + 1}` : null,
        start_ms: startMs,
        end_ms: endMs,
      };
      const previous = this.segments.at(-1);
      if (shouldReplacePreviousFinal(previous, segment, hasProviderTiming)) {
        this.segments[this.segments.length - 1] = segment;
      } else if (!shouldDropDuplicateFinal(previous, segment, hasProviderTiming)) {
        this.segments.push(segment);
      }
      this.lastFinalMs = Math.max(this.lastFinalMs, endMs);
      this.committedText = this.segments.map((item) => item.text).join(" ");
      this.interimText = "";
    } else {
      this.interimText = result.transcript;
    }
    this.opts.onUpdate?.({ committed: this.committedText, interim: this.interimText });
  }

  private recordRealtimeActivity(
    root: Record<string, unknown> | null,
    result: RealtimeResult | null,
  ): void {
    if (!root) return;
    const type = typeof root.type === "string" ? root.type : "";
    if (type === "UtteranceEnd") {
      this.markRealtimeEvent();
      return;
    }
    if (type === "Metadata" && this.didSendFinalize) {
      this.markRealtimeEvent(true);
      return;
    }
    if (root.from_finalize === true) {
      this.markRealtimeEvent(true);
      return;
    }
    if (result) {
      this.markRealtimeEvent();
    }
  }

  private markRealtimeEvent(finalizationMarker = false): void {
    this.lastRealtimeEventAt = Date.now();
    if (finalizationMarker) {
      this.finalizationMarkerReceived = true;
    }
  }

  async stop(): Promise<TranscriptSegmentInput[]> {
    if (this.state === "idle" || this.state === "stopping") return this.segments;
    this.stopRequested = true;
    this.setState("stopping");
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      this.cleanup();
      this.setState("idle");
      return this.segments;
    }
    try {
      this.sendStopControlPayload(ws, "Finalize");
      this.didSendFinalize = true;
      this.cleanupAudio();
      await this.waitForRealtimeDrain(ws, STOP_CLOSE_TIMEOUT_MS);
      if (ws.readyState === WebSocket.OPEN) {
        this.lastRealtimeEventAt = null;
        this.sendStopControlPayload(ws, "CloseStream");
        await this.waitForRealtimeDrain(ws, STOP_CLOSE_TIMEOUT_MS);
      }
      this.cleanupSocket();
      this.setState("idle");
      return this.segments;
    } catch (error) {
      this.cleanup();
      this.setState("error");
      throw error;
    }
  }

  private sendStopControlPayload(ws: WebSocket, type: "Finalize" | "CloseStream"): void {
    try {
      ws.send(JSON.stringify({ type }));
    } catch (error) {
      throw error instanceof Error ? error : new Error("Realtime transcription send failed.");
    }
  }

  private fail(error: unknown): void {
    this.opts.onError?.(error instanceof Error ? error.message : "Realtime transcription error");
    this.cleanup();
    this.setState("error");
  }

  private cleanup(): void {
    this.cleanupAudio();
    this.cleanupSocket();
  }

  private cleanupAudio(): void {
    if (this.keepAlive) clearInterval(this.keepAlive);
    this.keepAlive = null;
    try {
      this.node?.disconnect();
    } catch {
      /* already disconnected */
    }
    for (const source of this.sources) {
      try {
        source.disconnect();
      } catch {
        /* already disconnected */
      }
    }
    this.sources = [];
    if (this.ctx && this.ctx.state !== "closed") void this.ctx.close();
    this.ctx = null;
    this.node = null;
    this.clearPendingAudio();
    for (const stream of this.streams) {
      stream.getTracks().forEach((track) => track.stop());
    }
    this.streams = [];
  }

  private cleanupSocket(): void {
    if (this.ws) {
      try {
        if (
          this.ws.readyState === WebSocket.CONNECTING ||
          this.ws.readyState === WebSocket.OPEN
        ) {
          this.ws.close();
        }
      } catch {
        /* already closing */
      }
    }
    this.ws = null;
  }

  private waitForRealtimeDrain(ws: WebSocket, timeoutMs: number): Promise<void> {
    if (ws.readyState === WebSocket.CLOSED) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const previousOnClose = ws.onclose;
      const previousOnError = ws.onerror;
      let settled = false;
      let timer: ReturnType<typeof setTimeout> | null = null;
      const startedAt = Date.now();
      const deadlineAt = startedAt + timeoutMs;
      const finish = (settle: () => void): void => {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        ws.onclose = previousOnClose;
        ws.onerror = previousOnError;
        settle();
      };
      const poll = (): void => {
        if (
          ws.readyState === WebSocket.CLOSED ||
          !this.shouldKeepWaitingForRealtimeDrain(startedAt, deadlineAt)
        ) {
          finish(resolve);
          return;
        }
        timer = setTimeout(poll, REALTIME_DRAIN_POLL_INTERVAL_MS);
      };
      ws.onclose = () => finish(resolve);
      ws.onerror = () =>
        finish(() => reject(new Error("Realtime transcription connection failed during stop.")));
      poll();
    });
  }

  private shouldKeepWaitingForRealtimeDrain(startedAt: number, deadlineAt: number): boolean {
    const now = Date.now();
    if (now >= deadlineAt) return false;

    const minimumWaitUntil = startedAt + REALTIME_DRAIN_MINIMUM_WAIT_MS;
    if (this.finalizationMarkerReceived && now >= minimumWaitUntil) {
      return false;
    }

    if (this.lastRealtimeEventAt != null) {
      return !(
        now >= minimumWaitUntil &&
        now - this.lastRealtimeEventAt >= REALTIME_DRAIN_QUIET_WINDOW_MS
      );
    }

    return now < startedAt + REALTIME_DRAIN_NO_TRANSCRIPT_WAIT_MS;
  }
}

function parseRealtimeRoot(raw: string): Record<string, unknown> | null {
  try {
    const payload = JSON.parse(raw);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
    return payload as Record<string, unknown>;
  } catch {
    return null;
  }
}
