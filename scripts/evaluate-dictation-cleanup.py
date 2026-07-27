#!/usr/bin/env python3
"""Measure whether dictation smart cleanup preserves meaning, and how fast it is.

Cleanup is the one AI pass whose output lands directly in whatever the user is
typing into, so a dropped number or a paraphrased commitment is a data-loss bug,
not a style regression. Nothing in the product measured that until this script:
the only server-side check was a runaway-length guard.

The evaluator registers a throwaway account against the target API, walks the
fixture corpus (`dictation-cleanup-fixtures.json`) at each cleanup level, and
scores every response three ways:

- assertions  — must_keep / must_drop / never, the contract each fixture states
- retention   — share of the dictation's content tokens that survived
- addition    — share of the output's content tokens that were never dictated

Run against production for a baseline, or against a local backend to compare
prompt candidates:

    scripts/evaluate-dictation-cleanup.py
    scripts/evaluate-dictation-cleanup.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = ROOT / "scripts/dictation-cleanup-fixtures.json"
LATEST_OUTPUT = ROOT / "artifacts/benchmarks/dictation-cleanup-eval-latest.json"
DEFAULT_BASE_URL = "https://wai.computer"
DEFAULT_LEVELS = ("light", "medium", "high")
LEGAL_ACCEPTANCE = {
    "accepted_legal_terms": True,
    "legal_terms_version": "2026-05-22",
    "legal_privacy_version": "2026-05-22",
}

# Gates encode the product contract, not the current implementation: cleanup may
# reshape speech into writing, but it may not lose the speaker's content. A
# fixture assertion failing is always a bug; retention and addition catch the
# drift that no fixture happened to name.
GATE_THRESHOLDS = {
    "assertion_pass_rate": 1.0,
    "p95_latency_ms": 1_500,
}
# Applied to any fixture that does not state its own bounds — i.e. one where
# cleanup should delete nothing at all.
DEFAULT_MIN_RETENTION = 0.95
DEFAULT_MAX_ADDITION = 0.05

# Tokens the cleanup pass is explicitly allowed to delete, so their absence from
# the output is never counted as lost content.
FILLER_TOKENS = frozenset(
    """
    э ээ эээ а аа ааа ну вот типа значит короче как бы прям это самое
    um uh er ah like you well so basically actually right okay ok
    """.split()
)
# Function words carry no content on their own; dropping or reordering them is
# ordinary cleanup, so they stay out of the retention denominator.
STOPWORD_TOKENS = frozenset(
    """
    и а но или что чтобы как когда где если то же бы ли не ни да
    в во на за по из от до у к с со о об при для про над под без через
    я ты он она оно мы вы они мне тебе нам вам им его её их себе
    это этот эта эти тот та те там тут здесь так уже ещё еще
    the a an and or but if then that this these those there here
    is are was were be been being am do does did doing have has had
    i you he she it we they me him her us them my your his its our their
    to of in on at by for from with about into over under as not no
    """.split()
)
TOKEN_PATTERN = re.compile(r"[0-9]+(?:[.,][0-9]+)*|[^\W_]+", re.UNICODE)
# Typographic characters a model reaches for unprompted. None of them can be
# dictated, and each one breaks something downstream: a non-breaking hyphen
# fails a code search, a narrow space splits a number, curly quotes break a
# shell command. Tracked separately so they never masquerade as lost content.
SMART_PUNCTUATION = {
    "‑": "-",  # non-breaking hyphen
    "‐": "-",  # hyphen
    "–": "-",  # en dash
    " ": " ",  # no-break space
    " ": " ",  # narrow no-break space
    " ": " ",  # thin space
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "«": '"',
    "»": '"',
}


def plain_text(value: str) -> str:
    """Fold typographic characters back to their plain equivalents."""
    for fancy, plain in SMART_PUNCTUATION.items():
        value = value.replace(fancy, plain)
    return value


def smart_punctuation_introduced(raw: str, cleaned: str) -> list[str]:
    """Typographic characters the output added that the dictation never had."""
    return sorted(
        {
            character
            for character in SMART_PUNCTUATION
            if character in cleaned and character not in raw
        }
    )


@dataclass(frozen=True)
class Fixture:
    id: str
    language: str
    levels: tuple[str, ...]
    raw: str
    must_keep: tuple[str, ...]
    must_drop: tuple[str, ...]
    never: tuple[str, ...]
    note: str
    vocabulary: tuple[str, ...] = ()
    min_retention: float = DEFAULT_MIN_RETENTION
    max_addition: float = DEFAULT_MAX_ADDITION
    # Set when a fixture tracks a defect we have measured but not fixed. It is
    # still run and still reported — it just cannot fail the gate, so the gate
    # keeps catching new regressions instead of being permanently red.
    known_issue: str = ""


@dataclass
class Result:
    fixture_id: str
    level: str
    ok: bool
    latency_ms: int
    retention: float
    addition: float
    missing_keep: list[str] = field(default_factory=list)
    surviving_drop: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    smart_punctuation: list[str] = field(default_factory=list)
    over_deleted: bool = False
    over_added: bool = False
    known_issue: str = ""
    error: str | None = None
    raw_chars: int = 0
    cleaned_chars: int = 0
    # Safe to record: every fixture is synthetic, so no user dictation is ever
    # written to the artifact. Diagnosing drift is impossible without it.
    cleaned: str = ""


def load_fixtures(path: Path = FIXTURES_PATH) -> tuple[Fixture, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        Fixture(
            id=entry["id"],
            language=entry["language"],
            levels=tuple(entry["levels"]),
            raw=entry["raw"],
            must_keep=tuple(entry.get("must_keep", ())),
            must_drop=tuple(entry.get("must_drop", ())),
            never=tuple(entry.get("never", ())),
            note=entry.get("note", ""),
            vocabulary=tuple(entry.get("vocabulary", ())),
            min_retention=entry.get("min_retention", DEFAULT_MIN_RETENTION),
            max_addition=entry.get("max_addition", DEFAULT_MAX_ADDITION),
            known_issue=entry.get("known_issue", ""),
        )
        for entry in payload["fixtures"]
    )


def content_tokens(text: str) -> list[str]:
    """Tokens that carry meaning: no fillers, no function words, no single letters."""
    tokens = []
    for match in TOKEN_PATTERN.finditer(text.casefold()):
        token = match.group(0)
        if token in FILLER_TOKENS or token in STOPWORD_TOKENS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        tokens.append(token)
    return tokens


def retention_score(raw: str, cleaned: str) -> float:
    """Share of dictated content tokens still present after cleanup.

    Stem-tolerant on the tail: Russian cleanup legitimately re-inflects words
    when it fixes agreement, so a token counts as retained when a prefix of it
    survives. Anything shorter than the prefix window must match outright.
    """
    source = content_tokens(raw)
    if not source:
        return 1.0
    survivors = set(content_tokens(cleaned))
    stems = {token[:4] for token in survivors}
    kept = sum(
        1
        for token in source
        if token in survivors or (len(token) > 4 and token[:4] in stems)
    )
    return kept / len(source)


def addition_score(raw: str, cleaned: str) -> float:
    """Share of output content tokens that were never dictated."""
    produced = content_tokens(cleaned)
    if not produced:
        return 0.0
    source = set(content_tokens(raw))
    stems = {token[:4] for token in source}
    added = sum(
        1
        for token in produced
        if token not in source and not (len(token) > 4 and token[:4] in stems)
    )
    return added / len(produced)


def term_present(term: str, haystack: str) -> bool:
    """A `|`-separated term matches when any alternative survives.

    Cleanup is allowed to normalize a spoken number into digits, so a fixture
    can accept either spelling without weakening the assertion. Typography is
    folded first so a swapped hyphen shows up as a typography finding rather
    than as lost content.
    """
    folded = plain_text(haystack)
    return any(plain_text(option).casefold() in folded for option in term.split("|"))


def score(
    fixture: Fixture,
    level: str,
    cleaned: str,
    latency_ms: int,
    server_ms: int | None = None,
) -> Result:
    haystack = cleaned.casefold()
    missing_keep = [term for term in fixture.must_keep if not term_present(term, haystack)]
    surviving_drop = [term for term in fixture.must_drop if term_present(term, haystack)]
    invented = [term for term in fixture.never if term_present(term, haystack)]
    smart = smart_punctuation_introduced(fixture.raw, cleaned)
    retention = retention_score(fixture.raw, plain_text(cleaned))
    addition = addition_score(fixture.raw, plain_text(cleaned))
    over_deleted = retention < fixture.min_retention
    over_added = addition > fixture.max_addition
    return Result(
        fixture_id=fixture.id,
        level=level,
        ok=not (
            missing_keep or surviving_drop or invented or smart
            or over_deleted or over_added
        ),
        latency_ms=latency_ms,
        retention=retention,
        addition=addition,
        over_deleted=over_deleted,
        over_added=over_added,
        known_issue=fixture.known_issue,
        missing_keep=missing_keep,
        surviving_drop=surviving_drop,
        invented=invented,
        smart_punctuation=smart,
        raw_chars=len(fixture.raw),
        cleaned_chars=len(cleaned),
        cleaned=cleaned,
    )


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def summarize(results: list[Result]) -> dict[str, Any]:
    by_level: dict[str, dict[str, Any]] = {}
    for level in sorted({result.level for result in results}):
        rows = [result for result in results if result.level == level]
        scored = [row for row in rows if row.error is None and not row.known_issue]
        latencies = [float(row.latency_ms) for row in scored]
        by_level[level] = {
            "fixtures": len(rows),
            "errors": sum(1 for row in rows if row.error is not None),
            "assertion_pass_rate": (
                sum(1 for row in scored if row.ok) / len(scored) if scored else 0.0
            ),
            "min_retention": min((row.retention for row in scored), default=0.0),
            "mean_retention": (
                statistics.fmean(row.retention for row in scored) if scored else 0.0
            ),
            "max_addition": max((row.addition for row in scored), default=0.0),
            "mean_addition": (
                statistics.fmean(row.addition for row in scored) if scored else 0.0
            ),
            "p50_latency_ms": percentile(latencies, 0.50),
            "p95_latency_ms": percentile(latencies, 0.95),
            "max_latency_ms": max(latencies, default=0.0),
        }
    return by_level


def gate_failures(summary: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for level, stats in summary.items():
        if stats["errors"]:
            failures.append(f"{level}: {stats['errors']} request error(s)")
        if stats["assertion_pass_rate"] < GATE_THRESHOLDS["assertion_pass_rate"]:
            failures.append(
                f"{level}: assertion pass rate {stats['assertion_pass_rate']:.2f} "
                f"< {GATE_THRESHOLDS['assertion_pass_rate']:.2f}"
            )
        if stats["p95_latency_ms"] > GATE_THRESHOLDS["p95_latency_ms"]:
            failures.append(
                f"{level}: p95 latency {stats['p95_latency_ms']:.0f} ms "
                f"> {GATE_THRESHOLDS['p95_latency_ms']} ms"
            )
    return failures


async def register_user(client: httpx.AsyncClient) -> dict[str, str]:
    email = f"cleanup-eval-{uuid.uuid4().hex[:12]}@example.com"
    password = f"eval-{uuid.uuid4().hex}"
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, **LEGAL_ACCEPTANCE},
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def set_cleanup_level(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    level: str,
) -> None:
    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={"dictation_cleanup_level": level},
    )
    response.raise_for_status()


async def run_fixture(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    fixture: Fixture,
    level: str,
) -> Result:
    started = time.perf_counter()
    try:
        response = await client.post(
            "/api/dictation/cleanup",
            headers=headers,
            json={"text": fixture.raw, "vocabulary": list(fixture.vocabulary) or None},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return Result(
            fixture_id=fixture.id,
            level=level,
            ok=False,
            latency_ms=round((time.perf_counter() - started) * 1000),
            retention=0.0,
            addition=0.0,
            error=type(exc).__name__,
            raw_chars=len(fixture.raw),
        )
    latency_ms = round((time.perf_counter() - started) * 1000)
    return score(fixture, level, response.json()["text"], latency_ms)


def render(results: list[Result], summary: dict[str, dict[str, Any]]) -> str:
    lines = [
        f"{'fixture':<34}{'level':<8}{'ok':<6}{'ms':>6}{'keep':>7}{'add':>7}  notes",
    ]
    for result in results:
        notes = []
        if result.error:
            notes.append(f"error={result.error}")
        if result.missing_keep:
            notes.append("lost=" + ",".join(result.missing_keep))
        if result.surviving_drop:
            notes.append("kept=" + ",".join(result.surviving_drop))
        if result.invented:
            notes.append("invented=" + ",".join(result.invented))
        if result.smart_punctuation:
            notes.append("typography=" + "".join(result.smart_punctuation))
        if result.over_deleted:
            notes.append(f"over-deleted={result.retention:.2f}")
        if result.over_added:
            notes.append(f"over-added={result.addition:.2f}")
        lines.append(
            f"{result.fixture_id:<34}{result.level:<8}"
            f"{('ok' if result.ok else ('KNOWN' if result.known_issue else 'FAIL')):<6}"
            f"{result.latency_ms:>6}"
            f"{result.retention:>7.2f}{result.addition:>7.2f}  {'; '.join(notes)}"
        )
    lines.append("")
    for known in sorted({r.fixture_id: r for r in results if r.known_issue and not r.ok}.values(),
                        key=lambda r: r.fixture_id):
        lines.append(f"KNOWN ISSUE  {known.fixture_id}: {known.known_issue}")
    if any(r.known_issue and not r.ok for r in results):
        lines.append("")
    for level, stats in summary.items():
        lines.append(
            f"{level:<8} pass={stats['assertion_pass_rate']:.2f} "
            f"retention min={stats['min_retention']:.2f} mean={stats['mean_retention']:.2f} "
            f"addition max={stats['max_addition']:.2f} "
            f"latency p50={stats['p50_latency_ms']:.0f}ms p95={stats['p95_latency_ms']:.0f}ms"
        )
    return "\n".join(lines)


async def evaluate(
    base_url: str,
    levels: tuple[str, ...],
    repeats: int,
    only: tuple[str, ...] = (),
) -> int:
    fixtures = load_fixtures()
    if only:
        fixtures = tuple(fixture for fixture in fixtures if fixture.id in only)
        if not fixtures:
            raise SystemExit(f"No fixtures matched: {', '.join(only)}")
    results: list[Result] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        headers = await register_user(client)
        for level in levels:
            await set_cleanup_level(client, headers, level)
            for fixture in fixtures:
                if level not in fixture.levels:
                    continue
                for _ in range(repeats):
                    results.append(await run_fixture(client, headers, fixture, level))

    summary = summarize(results)
    print(render(results, summary))

    failures = gate_failures(summary)
    payload = {
        "base_url": base_url,
        "fixture_version": json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))["version"],
        "levels": list(levels),
        "repeats": repeats,
        "summary": summary,
        "gates": GATE_THRESHOLDS,
        "failures": failures,
        "results": [vars(result) for result in results],
    }
    LATEST_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    LATEST_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {LATEST_OUTPUT.relative_to(ROOT)}")

    if failures:
        print("\nGATE FAILURES")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nAll gates passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--levels",
        default=",".join(DEFAULT_LEVELS),
        help="Comma-separated cleanup levels to evaluate.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Runs per fixture; raise to sample non-determinism.",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated fixture ids to run instead of the whole corpus.",
    )
    args = parser.parse_args()
    levels = tuple(level.strip() for level in args.levels.split(",") if level.strip())
    only = tuple(item.strip() for item in args.only.split(",") if item.strip())
    return asyncio.run(evaluate(args.base_url, levels, args.repeats, only))


if __name__ == "__main__":
    sys.exit(main())
