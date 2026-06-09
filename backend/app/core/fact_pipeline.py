"""Bi-temporal fact reconciliation (P2) — supersede, never delete.

Given facts freshly extracted for a subject plus that subject's currently-valid
facts, decide per new fact:

- NOOP      — already stored (same content_hash, or same predicate+object).
- ADD       — genuinely new (no current fact with that predicate, or a
              multi-valued predicate where values coexist).
- SUPERSEDE — a single-valued predicate (e.g. employer) changed, OR the new fact
              carries an explicit ``supersedes_object`` hint: close the old fact's
              validity window (caller sets invalid_at + superseded_by_id) and add
              the new one. History is preserved, never deleted.
- CONFLICT  — a single-valued predicate has MULTIPLE current values so we can't be
              sure which to retire: add the new fact current AND flag it for one-tap
              review (the caller routes this to a MemoryProposal). No silent
              destruction.

This module is pure decision logic over plain dataclasses (no DB, no LLM), so it
is exhaustively unit-testable; the caller loads current facts and persists the
decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Predicates that hold at most ONE current value per subject — a new value
# retires the old. Everything else is multi-valued (knows, worked_on, attended)
# and new values coexist.
SINGLE_VALUED_PREDICATES = frozenset(
    {
        "works_at",
        "employed_by",
        "lives_in",
        "located_in",
        "based_in",
        "title",
        "role",
        "status",
        "manager",
        "owner",
        "married_to",
        "uses",
        "current_project",
    }
)


@dataclass(frozen=True)
class ExtractedFact:
    predicate: str
    object_text: str
    content_hash: str
    object_entity_id: str | None = None
    valid_at: datetime | None = None
    is_current: bool = True
    confidence: float = 1.0
    importance: float = 0.5
    supersedes_object: str | None = None  # explicit "this replaces <old object>"


@dataclass(frozen=True)
class CurrentFact:
    id: str
    predicate: str
    object_text: str
    content_hash: str


@dataclass(frozen=True)
class FactDecision:
    action: str  # "noop" | "add" | "supersede" | "conflict"
    fact: ExtractedFact
    supersedes_id: str | None = None  # current fact id to close (supersede/conflict)


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def decide_fact_actions(
    new_facts: list[ExtractedFact], current_facts: list[CurrentFact]
) -> list[FactDecision]:
    """Pure reconciliation: classify each new fact against the current ones."""
    seen_hashes = {f.content_hash for f in current_facts}
    by_pred_obj = {(_norm(f.predicate), _norm(f.object_text)): f for f in current_facts}
    by_pred: dict[str, list[CurrentFact]] = {}
    for f in current_facts:
        by_pred.setdefault(_norm(f.predicate), []).append(f)

    decisions: list[FactDecision] = []
    for nf in new_facts:
        pred, obj = _norm(nf.predicate), _norm(nf.object_text)

        if nf.content_hash in seen_hashes or (pred, obj) in by_pred_obj:
            decisions.append(FactDecision("noop", nf))
            continue

        same_pred = by_pred.get(pred, [])

        # Explicit "this replaces X" hint → close the matching old fact.
        if nf.supersedes_object is not None:
            target = next(
                (f for f in same_pred if _norm(f.object_text) == _norm(nf.supersedes_object)),
                None,
            )
            if target is not None:
                decisions.append(FactDecision("supersede", nf, supersedes_id=target.id))
                continue

        if same_pred and pred in SINGLE_VALUED_PREDICATES:
            if len(same_pred) == 1:
                decisions.append(FactDecision("supersede", nf, supersedes_id=same_pred[0].id))
            else:
                # Single-valued but several current values — ambiguous; add + review.
                decisions.append(FactDecision("conflict", nf, supersedes_id=same_pred[0].id))
            continue

        # New predicate, or a multi-valued predicate → values coexist.
        decisions.append(FactDecision("add", nf))

    return decisions
