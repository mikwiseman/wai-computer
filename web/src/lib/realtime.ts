// Browser realtime transcription client. Streams the mic (and optionally system
// audio) to the SAME proxy the Mac app uses: POST /api/transcription/session →
// open the WS (token via ?token=, since browsers can't set WS headers) → send
// 16 kHz Int16 PCM → render Deepgram interim/final results live → on stop,
// return the collected segments for finalization.

import { createTranscriptionSession } from "@/lib/api";
import { downsampleTo16kInt16 } from "@/lib/audio/pcm";
import type { RealtimeSessionResponse, TranscriptSegmentInput } from "@/lib/types";

export interface RealtimeResult {
  transcript: string;
  isFinal: boolean;
  speaker: number | null;
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
  return { transcript, isFinal, speaker };
}

export type RealtimeState = "idle" | "connecting" | "recording" | "stopping" | "error";

export interface RealtimeUpdate {
  committed: string;
  interim: string;
}

export interface RealtimeTranscriberOptions {
  language?: string;
  purpose?: "recording" | "dictation";
  onUpdate?: (update: RealtimeUpdate) => void;
  onState?: (state: RealtimeState) => void;
  onError?: (message: string) => void;
}

export class RealtimeTranscriber {
  private ctx: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private ws: WebSocket | null = null;
  private keepAlive: ReturnType<typeof setInterval> | null = null;
  private stream: MediaStream | null = null;
  private state: RealtimeState = "idle";
  private startedAt = 0;
  private lastFinalMs = 0;
  private committedText = "";
  private interimText = "";
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

  private setState(state: RealtimeState): void {
    this.state = state;
    this.opts.onState?.(state);
  }

  async start(stream: MediaStream): Promise<void> {
    if (this.state !== "idle") return;
    this.stream = stream;
    this.setState("connecting");
    let session: RealtimeSessionResponse;
    try {
      session = await createTranscriptionSession({
        language: this.opts.language,
        purpose: this.opts.purpose ?? "recording",
      });
    } catch (error) {
      this.fail(error);
      return;
    }
    try {
      await this.openSocket(session);
      await this.startAudio(stream);
      this.startedAt = Date.now();
      this.setState("recording");
    } catch (error) {
      this.fail(error);
    }
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
        const intervalMs = (session.keep_alive_interval_seconds ?? 8) * 1000;
        this.keepAlive = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "KeepAlive" }));
          }
        }, intervalMs);
        resolve();
      };
      ws.onmessage = (event) => this.onMessage(event);
      ws.onerror = () => reject(new Error("Realtime transcription connection failed"));
      ws.onclose = () => {
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

  private async startAudio(stream: MediaStream): Promise<void> {
    const ctx = new AudioContext();
    this.ctx = ctx;
    await ctx.audioWorklet.addModule("/realtime-pcm-worklet.js");
    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, "realtime-pcm-recorder");
    this.source = source;
    this.node = node;
    node.port.onmessage = (event) => {
      const float = event.data as Float32Array;
      const int16 = downsampleTo16kInt16(float, ctx.sampleRate);
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(int16.buffer);
      }
    };
    // Intentionally NOT connected to ctx.destination — monitoring would echo.
    source.connect(node);
  }

  private onMessage(event: MessageEvent): void {
    if (typeof event.data !== "string") return;
    const result = parseRealtimeMessage(event.data);
    if (!result) return;
    if (result.isFinal) {
      const startMs = this.lastFinalMs;
      const endMs = Date.now() - this.startedAt;
      this.lastFinalMs = endMs;
      this.segments.push({
        text: result.transcript,
        speaker: result.speaker != null ? `Speaker ${result.speaker + 1}` : null,
        start_ms: startMs,
        end_ms: endMs,
      });
      this.committedText = this.committedText
        ? `${this.committedText} ${result.transcript}`
        : result.transcript;
      this.interimText = "";
    } else {
      this.interimText = result.transcript;
    }
    this.opts.onUpdate?.({ committed: this.committedText, interim: this.interimText });
  }

  async stop(): Promise<TranscriptSegmentInput[]> {
    if (this.state === "idle" || this.state === "stopping") return this.segments;
    this.setState("stopping");
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify({ type: "CloseStream" }));
      } catch {
        // best-effort close frame
      }
    }
    this.cleanup();
    this.setState("idle");
    return this.segments;
  }

  private fail(error: unknown): void {
    this.opts.onError?.(error instanceof Error ? error.message : "Realtime transcription error");
    this.cleanup();
    this.setState("error");
  }

  private cleanup(): void {
    if (this.keepAlive) clearInterval(this.keepAlive);
    this.keepAlive = null;
    try {
      this.node?.disconnect();
    } catch {
      /* already disconnected */
    }
    try {
      this.source?.disconnect();
    } catch {
      /* already disconnected */
    }
    if (this.ctx && this.ctx.state !== "closed") void this.ctx.close();
    this.ctx = null;
    this.node = null;
    this.source = null;
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* already closing */
      }
    }
    this.ws = null;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
}
