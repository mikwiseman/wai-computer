"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { assignSpeaker, listPeople } from "@/lib/api";
import type { Person, RecordingDetail, Segment } from "@/lib/types";

interface SpeakerChipProps {
  segment: Segment;
  recordingId: string;
  onUpdated: (detail: RecordingDetail) => void;
}

function displayLabel(segment: Segment): string {
  return segment.display_name ?? segment.raw_label ?? segment.speaker ?? "Speaker";
}

export function SpeakerChip({ segment, recordingId, onUpdated }: SpeakerChipProps) {
  const [open, setOpen] = useState(false);
  const [people, setPeople] = useState<Person[] | null>(null);
  const [filter, setFilter] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open || people !== null) return;
    let cancelled = false;
    listPeople()
      .then((rows) => {
        if (!cancelled) setPeople(rows);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [open, people]);

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
    }
  }, [open]);

  const rawLabel = segment.raw_label ?? segment.speaker;
  const canAssign = typeof rawLabel === "string" && rawLabel.length > 0;

  const filtered = useMemo(() => {
    if (people === null) return [];
    const needle = filter.trim().toLowerCase();
    if (!needle) return people;
    return people.filter((p) => p.display_name.toLowerCase().includes(needle));
  }, [people, filter]);

  const exactMatch = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return null;
    return people?.find((p) => p.display_name.toLowerCase() === needle) ?? null;
  }, [people, filter]);

  async function handlePick(person: Person) {
    if (!canAssign || !rawLabel) return;
    setPending(true);
    setError(null);
    try {
      const detail = await assignSpeaker(recordingId, {
        raw_label: rawLabel,
        person_id: person.id,
      });
      onUpdated(detail);
      setOpen(false);
      setFilter("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to assign");
    } finally {
      setPending(false);
    }
  }

  async function handleCreate() {
    if (!canAssign || !rawLabel) return;
    const name = filter.trim();
    if (!name) return;
    setPending(true);
    setError(null);
    try {
      const detail = await assignSpeaker(recordingId, {
        raw_label: rawLabel,
        new_display_name: name,
      });
      onUpdated(detail);
      setOpen(false);
      setFilter("");
      setPeople(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to assign");
    } finally {
      setPending(false);
    }
  }

  const label = displayLabel(segment);
  const isAuto = segment.auto_assigned;
  const confidencePct =
    typeof segment.match_confidence === "number"
      ? Math.round(segment.match_confidence * 100)
      : null;

  return (
    <span className="speaker-chip-wrapper">
      <button
        type="button"
        className="speaker-chip"
        onClick={() => setOpen((value) => !value)}
        disabled={!canAssign || pending}
        style={
          segment.display_name && segment.person_id
            ? { backgroundColor: "var(--accent-50)", color: "var(--accent-700)" }
            : undefined
        }
        title={
          isAuto && confidencePct !== null
            ? `Auto-assigned (${confidencePct}% match) — click to override`
            : "Click to assign"
        }
      >
        <strong>{label}</strong>
        {isAuto && confidencePct !== null ? (
          <span aria-hidden="true" style={{ marginLeft: "0.25rem", fontSize: "0.7rem" }}>
            ✨{confidencePct}%
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="speaker-chip-popover" role="dialog">
          <input
            ref={inputRef}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Search or create…"
            type="text"
          />
          {error ? <div className="speaker-chip-error">{error}</div> : null}
          {people === null ? (
            <div className="speaker-chip-loading">Loading…</div>
          ) : (
            <ul className="speaker-chip-list">
              {filtered.map((person) => (
                <li key={person.id}>
                  <button
                    type="button"
                    disabled={pending}
                    onClick={() => handlePick(person)}
                  >
                    {person.display_name}
                  </button>
                </li>
              ))}
              {filter.trim() && !exactMatch ? (
                <li>
                  <button
                    type="button"
                    disabled={pending}
                    onClick={handleCreate}
                    className="speaker-chip-create"
                  >
                    + Create &ldquo;{filter.trim()}&rdquo;
                  </button>
                </li>
              ) : null}
              {filtered.length === 0 && !filter.trim() ? (
                <li className="speaker-chip-empty">
                  No people yet. Type a name above to create one.
                </li>
              ) : null}
            </ul>
          )}
        </div>
      ) : null}
    </span>
  );
}
