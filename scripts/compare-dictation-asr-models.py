#!/usr/bin/env python3
"""Compare realtime transcription models on the dictation fixture corpus.

The cleanup evaluator showed that after the prompt rewrite, every remaining
contract failure is an ASR failure: English technical terms spoken inside
Russian come back transliterated ("pull request" -> "пул реквест") or wrong
("I think" -> "айсинк"). No downstream edit pass can recover those, because the
word the decoder chose is gone.

`gpt-realtime-whisper` — the model dictation uses today — rejects the `prompt`
parameter outright, so the user's vocabulary cannot reach the decoder at all.
Other models on the same endpoint accept it. This measures what that is worth.

    scripts/compare-dictation-asr-models.py
    scripts/compare-dictation-asr-models.py --repeats 2

Talks straight to OpenAI so the model and its parameters are under test rather
than the proxy. Needs OPENAI_API_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.util
import json
import os
import statistics
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
AUDIO_CACHE = ROOT / "artifacts/benchmarks/dictation-audio"
LATEST_OUTPUT = ROOT / "artifacts/benchmarks/dictation-asr-models-latest.json"
URL = "wss://api.openai.com/v1/realtime?intent=transcription"
SAMPLE_RATE = 24_000
CHUNK_MS = 100


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SCORING = _load("evaluate_dictation_cleanup", "evaluate-dictation-cleanup.py")
AUDIO = _load("compare_dictation_raw_vs_cleanup", "compare-dictation-raw-vs-cleanup.py")

# The vocabulary a real user of this product would have: their own product
# names plus the English engineering terms they say inside Russian sentences.
# This is exactly what the backend already stores as dictionary words, People
# and project/organization entities — today it is spent on the cleanup prompt.
VOCABULARY_HINT = (
    "Термины, которые встречаются в речи: WaiComputer, Sentry, Amplitude, macOS, "
    "PDF, pull request, main, realtime bridge, review, deploy, feature flag, "
    "MFC-482, docker compose, wai.computer, онбординг, биллинг."
)


@dataclass(frozen=True)
class Candidate:
    label: str
    model: str
    prompt: str | None = None
    delay: str | None = None


CANDIDATES = (
    Candidate("whisper (current)", "gpt-realtime-whisper", None, "high"),
    Candidate("whisper delay=low", "gpt-realtime-whisper", None, "low"),
    Candidate("4o-transcribe", "gpt-4o-transcribe"),
    Candidate("4o-transcribe +vocab", "gpt-4o-transcribe", VOCABULARY_HINT),
    Candidate("4o-mini-transcribe", "gpt-4o-mini-transcribe"),
    Candidate("4o-mini-transcribe +vocab", "gpt-4o-mini-transcribe", VOCABULARY_HINT),
)


@dataclass
class Row:
    candidate: str
    fixture_id: str
    ok: bool
    latency_ms: int
    retention: float
    missing: list[str] = field(default_factory=list)
    text: str = ""
    error: str | None = None


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as handle:
        return handle.readframes(handle.getnframes())


async def transcribe(key: str, candidate: Candidate, pcm: bytes, language: str) -> tuple[str, int]:
    transcription: dict[str, object] = {"model": candidate.model, "language": language}
    if candidate.delay:
        transcription["delay"] = candidate.delay
    if candidate.prompt:
        transcription["prompt"] = candidate.prompt
    session = {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                    "transcription": transcription,
                    "noise_reduction": {"type": "near_field"},
                    "turn_detection": None,
                }
            },
        },
    }
    async with websockets.connect(
        URL, additional_headers={"Authorization": f"Bearer {key}"}, max_size=8 * 1024 * 1024
    ) as ws:
        await ws.send(json.dumps(session))
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            if message.get("type") == "session.updated":
                break
            if message.get("type") == "error":
                raise RuntimeError(str(message["error"].get("message"))[:90])

        step = SAMPLE_RATE * 2 * CHUNK_MS // 1000
        for index in range(0, len(pcm), step):
            frame = base64.b64encode(pcm[index : index + step]).decode()
            await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": frame}))
            await asyncio.sleep(0.01)
        committed = time.perf_counter()
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

        parts: list[str] = []
        while True:
            try:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
            except TimeoutError:
                break
            kind = message.get("type", "")
            if kind.endswith("transcription.completed"):
                parts.append(message.get("transcript", ""))
                break
            if message.get("type") == "error":
                raise RuntimeError(str(message["error"].get("message"))[:90])
    return " ".join(parts).strip(), round((time.perf_counter() - committed) * 1000)


def render(rows: list[Row]) -> str:
    lines = [f"{'candidate':<28}{'pass':>6}{'retention':>11}{'p50 ms':>9}{'p95 ms':>9}  worst misses"]
    for candidate in dict.fromkeys(row.candidate for row in rows):
        scored = [r for r in rows if r.candidate == candidate and r.error is None]
        if not scored:
            continue
        latencies = sorted(r.latency_ms for r in scored)
        misses: dict[str, int] = {}
        for row in scored:
            for term in row.missing:
                misses[term] = misses.get(term, 0) + 1
        worst = ", ".join(
            term.split("|")[0] for term, _ in sorted(misses.items(), key=lambda kv: -kv[1])[:5]
        )
        lines.append(
            f"{candidate:<28}"
            f"{sum(1 for r in scored if r.ok) / len(scored):>6.2f}"
            f"{statistics.fmean(r.retention for r in scored):>11.2f}"
            f"{latencies[len(latencies) // 2]:>9}"
            f"{latencies[min(len(latencies) - 1, int(0.95 * (len(latencies) - 1)))]:>9}"
            f"  {worst}"
        )
    return "\n".join(lines)


async def sweep(repeats: int, only: tuple[str, ...]) -> int:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit("OPENAI_API_KEY is required")
    fixtures = [f for f in SCORING.load_fixtures() if not only or f.id in only]
    rows: list[Row] = []
    for candidate in CANDIDATES:
        for fixture in fixtures:
            path = AUDIO_CACHE / f"{fixture.id}.wav"
            if not path.exists():
                AUDIO.synthesize(fixture.id, fixture.raw, fixture.language)
            pcm = read_pcm(path)
            language = "en" if fixture.language == "en" else "ru"
            for _ in range(repeats):
                try:
                    text, latency = await transcribe(key, candidate, pcm, language)
                except Exception as exc:  # noqa: BLE001 - the failure is the datum
                    rows.append(
                        Row(candidate.label, fixture.id, False, 0, 0.0, error=str(exc)[:90])
                    )
                    continue
                # Only must_keep applies: raw ASR is not asked to drop fillers
                # or apply spoken corrections, just to hear the words.
                missing = [
                    term
                    for term in fixture.must_keep
                    if not SCORING.term_present(term, text.casefold())
                ]
                rows.append(
                    Row(
                        candidate=candidate.label,
                        fixture_id=fixture.id,
                        ok=not missing,
                        latency_ms=latency,
                        retention=SCORING.retention_score(fixture.raw, text),
                        missing=missing,
                        text=text,
                    )
                )
        print(f"  … {candidate.label} done", flush=True)

    print()
    print(render(rows))
    LATEST_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    LATEST_OUTPUT.write_text(
        json.dumps({"vocabulary": VOCABULARY_HINT, "rows": [vars(r) for r in rows]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote {LATEST_OUTPUT.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    only = tuple(item.strip() for item in args.only.split(",") if item.strip())
    return asyncio.run(sweep(args.repeats, only))


if __name__ == "__main__":
    sys.exit(main())
