#!/usr/bin/env python3
"""Answer one question: is the LLM cleanup pass earning its latency?

Dictation is two calls today — realtime ASR, then a cleanup LLM. This speaks
the fixture corpus aloud, streams it through the real realtime pipeline, and
scores the RAW transcript against exactly the same contract the cleaned text
is scored against. Whatever the raw transcript already satisfies is work the
second call is repeating.

    scripts/compare-dictation-raw-vs-cleanup.py --base-url https://wai.computer

Audio is macOS `say`, so the disfluencies are synthesised rather than human.
That is a real limitation and it cuts one way only: synthetic speech is
*cleaner* than a real speaker, so anything the raw transcript still gets wrong
here is a floor on the problem, not a ceiling.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = ROOT / "scripts/dictation-cleanup-fixtures.json"
AUDIO_CACHE = ROOT / "artifacts/benchmarks/dictation-audio"
LATEST_OUTPUT = ROOT / "artifacts/benchmarks/dictation-raw-vs-cleanup-latest.json"
SAMPLE_RATE = 24_000
BYTES_PER_SAMPLE = 2
CHUNK_MS = 100
FINAL_SILENCE_MS = 300
VOICES = {"ru": "Milena", "en": "Samantha", "mixed": "Milena"}
LEGAL_ACCEPTANCE = {
    "accepted_legal_terms": True,
    "legal_terms_version": "2026-05-22",
    "legal_privacy_version": "2026-05-22",
}


def _scoring():
    """Reuse the cleanup evaluator's scoring so both halves are judged alike."""
    path = ROOT / "scripts/evaluate-dictation-cleanup.py"
    spec = importlib.util.spec_from_file_location("evaluate_dictation_cleanup", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCORING = _scoring()


@dataclass
class Comparison:
    fixture_id: str
    level: str
    raw_ok: bool
    cleaned_ok: bool
    raw_missing: list[str] = field(default_factory=list)
    cleaned_missing: list[str] = field(default_factory=list)
    raw_surviving_drop: list[str] = field(default_factory=list)
    cleaned_surviving_drop: list[str] = field(default_factory=list)
    raw_has_sentence_case: bool = False
    raw_has_terminal_punctuation: bool = False
    asr_ms: int = 0
    cleanup_ms: int = 0
    raw_text: str = ""
    cleaned_text: str = ""
    error: str | None = None


def require(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Required command not found: {name}")


def synthesize(fixture_id: str, text: str, language: str) -> bytes:
    """Speak the dictation once and cache it; `say` is slow and deterministic."""
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    wav_path = AUDIO_CACHE / f"{fixture_id}.wav"
    if not wav_path.exists():
        require("say")
        require("afconvert")
        aiff = wav_path.with_suffix(".aiff")
        subprocess.run(
            ["say", "-v", VOICES.get(language, "Milena"), "-o", str(aiff), text],
            check=True,
        )
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", str(aiff), str(wav_path)],
            check=True,
        )
        aiff.unlink(missing_ok=True)
    with wave.open(str(wav_path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (
            SAMPLE_RATE,
            1,
            2,
        ):
            raise SystemExit(f"{wav_path} is not {SAMPLE_RATE} Hz mono int16")
        return wav.readframes(wav.getnframes())


def chunks(pcm: bytes) -> list[bytes]:
    size = SAMPLE_RATE * BYTES_PER_SAMPLE * CHUNK_MS // 1000
    return [pcm[index : index + size] for index in range(0, len(pcm), size)]


def silence(ms: int = FINAL_SILENCE_MS) -> bytes:
    return b"\x00" * (SAMPLE_RATE * BYTES_PER_SAMPLE * ms // 1000)


def frame_transcript(raw: str | bytes) -> tuple[str | None, bool, bool]:
    """(text, is_final, finalization_marker) from one Deepgram-shaped frame."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, False, False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, False, False
    kind = payload.get("type")
    if kind == "Results":
        alternatives = payload.get("channel", {}).get("alternatives", [])
        text = (alternatives[0].get("transcript") if alternatives else None) or None
        if text:
            text = " ".join(text.split())
        return text, bool(payload.get("is_final")), bool(payload.get("from_finalize"))
    if kind == "Metadata":
        return None, False, True
    if kind in {"Error", "error"}:
        raise RuntimeError(payload.get("message") or payload.get("description") or "realtime error")
    return None, False, False


async def transcribe(session: dict[str, Any], pcm: bytes) -> tuple[str, int]:
    """Stream the audio and return the final raw transcript plus finalize latency."""
    url = session["websocket_url"]
    headers = {"Authorization": f"Bearer {session['token']}"}
    segments: list[str] = []
    send_done = asyncio.Event()
    last_audio_at = 0.0
    last_final_at = 0.0
    finalized = False

    async with websockets.connect(url, additional_headers=headers, max_size=8 * 1024 * 1024) as ws:
        async def send_loop() -> None:
            nonlocal last_audio_at
            try:
                for chunk in chunks(pcm):
                    await ws.send(chunk)
                    await asyncio.sleep(CHUNK_MS / 1000)
                await ws.send(silence())
                last_audio_at = time.perf_counter()
                await ws.send(json.dumps({"type": "Finalize"}))
            finally:
                send_done.set()

        async def receive_loop() -> None:
            nonlocal finalized, last_final_at
            while True:
                try:
                    timeout = 4.0 if send_done.is_set() else 12.0
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except (TimeoutError, ConnectionClosed):
                    return
                text, is_final, marker = frame_transcript(raw)
                if marker:
                    finalized = True
                if text and is_final:
                    if not segments or segments[-1] != text:
                        segments.append(text)
                    last_final_at = time.perf_counter()
                if finalized and not text:
                    return

        sender = asyncio.create_task(send_loop())
        try:
            await receive_loop()
        finally:
            sender.cancel()

    finalize_ms = (
        round((last_final_at - last_audio_at) * 1000)
        if last_audio_at and last_final_at > last_audio_at
        else 0
    )
    return " ".join(segments).strip(), finalize_ms


def sentence_case(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped[0].isupper()


def terminal_punctuation(text: str) -> bool:
    return text.strip().endswith((".", "!", "?", ":", "»", '"'))


async def register(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/auth/register",
        json={
            "email": f"raw-vs-cleanup-{uuid.uuid4().hex[:12]}@example.com",
            "password": f"eval-{uuid.uuid4().hex}",
            **LEGAL_ACCEPTANCE,
        },
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def mint_session(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    language: str,
) -> dict[str, Any]:
    response = await client.post(
        "/api/transcription/session",
        headers=headers,
        json={"language": language, "channels": 1, "purpose": "dictation"},
    )
    response.raise_for_status()
    return response.json()


def render(rows: list[Comparison]) -> str:
    lines = [
        f"{'fixture':<34}{'level':<8}{'raw':<6}{'clean':<7}"
        f"{'asr_ms':>7}{'cln_ms':>7}  raw gaps"
    ]
    for row in rows:
        gaps = []
        if row.error:
            gaps.append(f"error={row.error}")
        if row.raw_missing:
            gaps.append("lost=" + ",".join(row.raw_missing))
        if row.raw_surviving_drop:
            gaps.append("kept=" + ",".join(row.raw_surviving_drop))
        if not row.raw_has_sentence_case:
            gaps.append("no-caps")
        if not row.raw_has_terminal_punctuation:
            gaps.append("no-punct")
        lines.append(
            f"{row.fixture_id:<34}{row.level:<8}"
            f"{('ok' if row.raw_ok else 'FAIL'):<6}{('ok' if row.cleaned_ok else 'FAIL'):<7}"
            f"{row.asr_ms:>7}{row.cleanup_ms:>7}  {'; '.join(gaps)}"
        )
    scored = [row for row in rows if row.error is None]
    if scored:
        raw_pass = sum(1 for row in scored if row.raw_ok) / len(scored)
        clean_pass = sum(1 for row in scored if row.cleaned_ok) / len(scored)
        caps = sum(1 for row in scored if row.raw_has_sentence_case) / len(scored)
        punct = sum(1 for row in scored if row.raw_has_terminal_punctuation) / len(scored)
        lines += [
            "",
            f"raw ASR       contract pass {raw_pass:.2f}   "
            f"sentence case {caps:.2f}   terminal punctuation {punct:.2f}",
            f"after cleanup contract pass {clean_pass:.2f}",
            f"cleanup adds  {sum(r.cleanup_ms for r in scored) / len(scored):.0f} ms per dictation "
            f"on top of {sum(r.asr_ms for r in scored) / len(scored):.0f} ms of finalize",
        ]
    return "\n".join(lines)


async def compare(base_url: str, level: str, only: tuple[str, ...]) -> int:
    fixtures = [f for f in SCORING.load_fixtures() if level in f.levels]
    if only:
        fixtures = [f for f in fixtures if f.id in only]
    if not fixtures:
        raise SystemExit("No fixtures selected")

    rows: list[Comparison] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=120.0) as client:
        headers = await register(client)
        await client.patch(
            "/api/settings", headers=headers, json={"dictation_cleanup_level": level}
        )
        for fixture in fixtures:
            try:
                pcm = synthesize(fixture.id, fixture.raw, fixture.language)
                session = await mint_session(
                    client, headers, "ru" if fixture.language != "en" else "en"
                )
                raw_text, asr_ms = await transcribe(session, pcm)
                if not raw_text:
                    raise RuntimeError("empty transcript")
                started = time.perf_counter()
                response = await client.post(
                    "/api/dictation/cleanup", headers=headers, json={"text": raw_text}
                )
                response.raise_for_status()
                cleaned_text = response.json()["text"]
                cleanup_ms = round((time.perf_counter() - started) * 1000)
            except Exception as exc:  # noqa: BLE001 - the failure itself is the datum
                rows.append(
                    Comparison(
                        fixture_id=fixture.id,
                        level=level,
                        raw_ok=False,
                        cleaned_ok=False,
                        error=f"{type(exc).__name__}: {exc}"[:120],
                    )
                )
                continue

            raw_score = SCORING.score(fixture, level, raw_text, 0)
            cleaned_score = SCORING.score(fixture, level, cleaned_text, cleanup_ms)
            rows.append(
                Comparison(
                    fixture_id=fixture.id,
                    level=level,
                    raw_ok=not (raw_score.missing_keep or raw_score.surviving_drop),
                    cleaned_ok=not (
                        cleaned_score.missing_keep or cleaned_score.surviving_drop
                    ),
                    raw_missing=raw_score.missing_keep,
                    cleaned_missing=cleaned_score.missing_keep,
                    raw_surviving_drop=raw_score.surviving_drop,
                    cleaned_surviving_drop=cleaned_score.surviving_drop,
                    raw_has_sentence_case=sentence_case(raw_text),
                    raw_has_terminal_punctuation=terminal_punctuation(raw_text),
                    asr_ms=asr_ms,
                    cleanup_ms=cleanup_ms,
                    raw_text=raw_text,
                    cleaned_text=cleaned_text,
                )
            )

    print(render(rows))
    LATEST_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    LATEST_OUTPUT.write_text(
        json.dumps(
            {"base_url": base_url, "level": level, "results": [vars(r) for r in rows]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {LATEST_OUTPUT.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://wai.computer")
    parser.add_argument("--level", default="medium")
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    only = tuple(item.strip() for item in args.only.split(",") if item.strip())
    return asyncio.run(compare(args.base_url, args.level, only))


if __name__ == "__main__":
    sys.exit(main())
