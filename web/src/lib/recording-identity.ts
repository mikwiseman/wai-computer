import type { RecordingDetail } from "./types";

/**
 * The dashboard polls the full recording detail every 2.5s while anything is
 * processing. Each response is a brand-new object graph, which would invalidate
 * every memoized transcript row (thousands on a long meeting) even when nothing
 * changed. This merge preserves referential identity where the data is
 * structurally identical:
 *
 * - nothing changed        → returns `prev` (React bails out of the state set)
 * - only scalars changed   → returns `next` with `prev.segments` carried over
 * - transcript changed     → returns `next` untouched
 *
 * Comparison is JSON-based: both objects come from the same deserializer, so
 * key order is stable, and the poll cadence (2.5s) makes the stringify cost
 * (~1ms per few thousand segments) irrelevant next to the reconcile it avoids.
 */
export function preserveRecordingDetailIdentity(
  prev: RecordingDetail | null,
  next: RecordingDetail,
): RecordingDetail {
  if (!prev || prev.id !== next.id) return next;

  const segmentsUnchanged =
    prev.segments === next.segments ||
    JSON.stringify(prev.segments) === JSON.stringify(next.segments);
  if (!segmentsUnchanged) return next;

  const restUnchanged =
    JSON.stringify({ ...prev, segments: null }) ===
    JSON.stringify({ ...next, segments: null });
  if (restUnchanged) return prev;

  return { ...next, segments: prev.segments };
}
