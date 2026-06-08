import type { AuthLocale } from "./auth-locale";
import { formatSpeakerLabel, formatTimestamp } from "./format";
import type { Segment } from "./types";

/**
 * Transcript rendering styles. The recogniser emits short, pause-split utterances;
 * rendering one per line with a repeated `[Speaker, time]` prefix is unreadable.
 * Merging consecutive same-speaker utterances into turns is the shared primitive
 * (mirrors the backend `merge_segment_turns`), and these styles render the result:
 *
 * - `plain`: flowing paragraphs, no timestamps; labels dropped entirely for a
 *   single-speaker recording (the "just give me the text" case).
 * - `speakers`: like `plain` but always shows the speaker label.
 * - `timestamped`: `[Speaker, M:SS] text` per turn (today's look, merged).
 */
export type TranscriptStyle = "plain" | "speakers" | "timestamped";

export interface TranscriptTurn {
  /** Stable grouping identity (`person:<id>` / `speaker:<n>` / raw label / ""). */
  key: string;
  /** Resolved human display label for the turn (e.g. "Speaker 1", "Anna"). */
  speaker: string;
  startMs: number | null;
  text: string;
  /** Source utterances; `segments[0]` drives the interactive speaker chip in the view. */
  segments: Segment[];
}

const CLOSING_PUNCT = new Set([",", ".", ";", ":", "!", "?", ")", "»", "”"]);

/** Mirrors the backend `_segment_speaker_key`: identity for turn grouping. */
function segmentSpeakerKey(seg: Segment): string {
  if (seg.person_id) return `person:${seg.person_id}`;
  const raw = (seg.speaker ?? seg.raw_label ?? "").trim();
  const match = /^(?:speaker|спикер)[\s_-]*(\d+)$/i.exec(raw);
  if (match) return `speaker:${Number(match[1])}`;
  return raw.toLowerCase();
}

/** Join two utterance fragments with a single space, except before closing punctuation. */
function joinFragments(existing: string, addition: string): string {
  if (!existing) return addition;
  if (!addition) return existing;
  if (CLOSING_PUNCT.has(addition[0]!)) return existing + addition;
  return `${existing} ${addition}`;
}

/**
 * Merge consecutive segments with the same resolved speaker into readable turns.
 * Segments are ordered by `start_ms` (missing timestamps sort last, stably) and
 * empty-content segments are dropped.
 */
export function mergeTurns(segments: Segment[], locale: AuthLocale = "en"): TranscriptTurn[] {
  const ordered = [...segments].sort((a, b) => {
    const aNull = a.start_ms == null;
    const bNull = b.start_ms == null;
    if (aNull !== bNull) return aNull ? 1 : -1;
    return (a.start_ms ?? 0) - (b.start_ms ?? 0);
  });

  const turns: TranscriptTurn[] = [];
  let current: TranscriptTurn | null = null;
  for (const seg of ordered) {
    const text = (seg.content ?? "").trim();
    if (!text) continue;
    const key = segmentSpeakerKey(seg);
    if (current && key === current.key) {
      current.text = joinFragments(current.text, text);
      current.segments.push(seg);
    } else {
      if (current) turns.push(current);
      current = {
        key,
        speaker: formatSpeakerLabel(seg.speaker, seg.raw_label, seg.display_name, locale),
        startMs: seg.start_ms,
        text,
        segments: [seg],
      };
    }
  }
  if (current) turns.push(current);
  return turns;
}

/** Render merged turns as a transcript string in the requested style. */
export function renderTranscript(turns: TranscriptTurn[], style: TranscriptStyle): string {
  if (turns.length === 0) return "";

  if (style === "timestamped") {
    return turns
      .map((turn) => {
        const ts = formatTimestamp(turn.startMs);
        return ts ? `[${turn.speaker}, ${ts}] ${turn.text}` : `[${turn.speaker}] ${turn.text}`;
      })
      .join("\n");
  }

  const distinct = new Set(turns.map((turn) => turn.key));
  const showLabels = style === "speakers" || distinct.size > 1;
  return turns
    .map((turn) => (showLabels ? `${turn.speaker}: ${turn.text}` : turn.text))
    .join("\n\n");
}

/** Convenience: merge + render in one call (used by copy buttons). */
export function transcriptText(
  segments: Segment[],
  style: TranscriptStyle,
  locale: AuthLocale = "en",
): string {
  return renderTranscript(mergeTurns(segments, locale), style);
}
