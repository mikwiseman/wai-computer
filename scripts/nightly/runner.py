"""WaiSay nightly QA harness — Tier 1.

Generates TTS audio from Inworld, streams it through Inworld STT, computes WER
and latency vs ground-truth text, writes structured report.

Run: ./scripts/nightly/run.sh
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import math
import os
import statistics
import sys
import time
import urllib.request
import wave
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websockets

logger = logging.getLogger("nightly")

INWORLD_TTS_URL = "https://api.inworld.ai/tts/v1/voice"
INWORLD_STT_WS = "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
TTS_MODEL = "inworld-tts-1.5-max"
STT_MODEL = "soniox/stt-rt-v4"
# Keep in sync with backend/app/config.py::Settings.anthropic_dictation_model.
CLEANUP_MODEL = "claude-haiku-4-5"
SAMPLE_RATE = 16000
CHUNK_MS = 50

# Verbatim copy of backend/app/api/routes/dictation.py::cleanup_dictation prompt.
# Update both files together if either changes — the harness's job is to detect
# regressions in this exact prompt.
_CLEANUP_PROMPT_TEMPLATE = (
    "Lightly clean up this dictated text. "
    "Remove filler sounds and filler words in Russian and English, including "
    "э, эээ, э-э-э, а, ааа, а-а-а, ну, вот, типа, как бы, значит, "
    "um, uh, like, you know, I mean, basically, actually, so, well. "
    "Remove repeated filler-only loops such as 'и, э-э-э, и, э-э-э'. "
    "Remove false starts and self-corrections, keeping only the final intended "
    "version, for example 'мы х-- мы предлагаем' becomes 'мы предлагаем'. "
    "Fix only obvious grammar, capitalization, and punctuation issues. "
    "Preserve the original language, meaning, tone, style, terminology, names, "
    "claims, and sentence order. "
    "Do not summarize, add information, change the meaning, or make it more "
    "formal unless the text is clearly formal already. "
    "Output ONLY the cleaned text, nothing else.\n\n"
    "Dictated text: {text}"
)


@dataclass
class ScenarioResult:
    id: str
    category: str
    language: str
    voice: str
    expected: str
    transcript: str
    wer: float
    e2e_latency_ms: float
    tts_ms: float
    stt_ms: float
    status: str
    # Perceived-latency breakdown. Both anchored to the moment we sent the
    # first audio chunk (== STT session start). first_final_ms is when the
    # first isFinal=true frame arrived; useful for comparing against the
    # Wispr Flow <250ms "end-of-speech to first text" benchmark when the
    # scenario is short enough that the only final IS the post-audio one.
    stt_first_interim_ms: float = 0.0
    stt_first_final_ms: float = 0.0
    # Tier 1.5 — only populated when scenario has `apply_cleanup: true`.
    # cleaned_transcript is the post-Anthropic output; clean_wer compares
    # it against scenario.cleaned_expected; cleanup_ms is the wall-clock
    # round-trip to the Anthropic API.
    cleaned_transcript: str = ""
    clean_wer: float = 0.0
    cleanup_ms: float = 0.0
    notes: list[str] = field(default_factory=list)


def normalize(text: str) -> list[str]:
    keep = []
    for ch in text.lower():
        if ch.isalnum() or ch.isspace():
            keep.append(ch)
        else:
            keep.append(" ")
    return "".join(keep).split()


_PUNCT_LEFT_ATTACH = ",.;:!?)]}\"'"


def merge_finals(segments: list[str]) -> str:
    """Reconstruct a clean transcript from Inworld STT final segments.

    Empirically observed Inworld STT (Soniox v4 RT) protocol via NIGHTLY_TRACE
    logs on long-form audio:

      - When a new final begins a NEW WORD, the segment text starts with a
        single leading space (e.g. " agreed on three top priorities...").
      - When a new final continues MID-WORD (rare; happens when silence-VAD
        boundary lands inside a word like "qu"+"arter"), the segment has no
        leading space and starts with an alnum char.
      - Punctuation that attaches left (",.;:!?)]}\\"'") may appear at the
        start of a final without a leading space.

    Heuristic (in order):
      1. Punctuation-left-attach -> no space
      2. Leading whitespace in raw -> add a single space
      3. Both boundary chars alnum (no leading ws) -> mid-word, no space
      4. Anything else -> add a single space

    The parser MUST pass raw text (not pre-stripped) for rules 2 and 3 to work.
    """
    if not segments:
        return ""
    parts: list[str] = []
    for raw in segments:
        if not raw:
            continue
        stripped = raw.lstrip()
        if not stripped:
            continue
        if not parts:
            parts.append(stripped)
            continue
        prev = parts[-1].rstrip()
        if not prev:
            parts[-1] = stripped
            continue
        parts[-1] = prev
        first_char = stripped[0]
        last_char = prev[-1]
        leading_ws = raw != stripped
        if first_char in _PUNCT_LEFT_ATTACH:
            parts.append(stripped)
        elif leading_ws:
            parts.append(" " + stripped)
        elif last_char.isalnum() and first_char.isalnum():
            parts.append(stripped)
        else:
            parts.append(" " + stripped)
    return "".join(parts).strip()


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate via Levenshtein on word tokens."""
    ref = normalize(reference)
    hyp = normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
                dp[i - 1][j - 1] + cost,
            )
    return dp[n][m] / n


def load_anthropic_key() -> str | None:
    """Returns the Anthropic key for cleanup tests, or None if not configured.

    Tier 1.5 is opt-in per scenario; if the key is missing we skip cleanup
    rather than fail the run. Fetch with:
      ssh <release-user>@<release-host> 'grep ^ANTHROPIC_API_KEY= /etc/waisay/backend.env' \\
        > ~/.config/waisay/anthropic.env && chmod 600 ~/.config/waisay/anthropic.env
    """
    candidate = Path.home() / ".config" / "waisay" / "anthropic.env"
    if not candidate.exists():
        return None
    raw = candidate.read_text().strip()
    if "=" in raw:
        raw = raw.split("=", 1)[1].strip().strip("\"'")
    return raw or None


def clean_with_anthropic(api_key: str, text: str) -> tuple[str, float]:
    """Replicates backend/app/api/routes/dictation.py::cleanup_dictation.

    Returns (cleaned_text, wall_clock_ms). Mirrors backend's early-returns:
    empty input -> "", input < 10 chars -> input unchanged (no API call).
    """
    text = text.strip()
    if not text:
        return "", 0.0
    if len(text) < 10:
        return text, 0.0
    body = {
        "model": CLEANUP_MODEL,
        "max_tokens": 4096,
        "messages": [
            {"role": "user", "content": _CLEANUP_PROMPT_TEMPLATE.format(text=text)},
        ],
    }
    req = urllib.request.Request(
        ANTHROPIC_MESSAGES_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read())
    elapsed_ms = (time.perf_counter() - t0) * 1000
    blocks = payload.get("content") or []
    if not blocks:
        raise RuntimeError(f"anthropic response empty: keys={list(payload.keys())}")
    cleaned = (blocks[0].get("text") or "").strip()
    if not cleaned:
        raise RuntimeError("anthropic returned empty text block")
    return cleaned, elapsed_ms


def load_inworld_key() -> str:
    candidate = Path.home() / ".config" / "waisay" / "inworld.env"
    if not candidate.exists():
        raise RuntimeError(
            f"INWORLD_API_KEY missing. Expected at {candidate} (mode 0600).\n"
            "Fetch with: ssh <release-user>@<release-host> 'grep ^INWORLD_API_KEY= /etc/waisay/backend.env' "
            "> ~/.config/waisay/inworld.env && chmod 600 ~/.config/waisay/inworld.env"
        )
    raw = candidate.read_text().strip()
    if "=" in raw:
        raw = raw.split("=", 1)[1].strip().strip("\"'")
    if not raw:
        raise RuntimeError(f"INWORLD_API_KEY at {candidate} is empty")
    # Normalize per backend/app/core/inworld.py: if `id:secret`, base64-encode for HTTP Basic.
    if ":" in raw:
        raw = base64.b64encode(raw.encode()).decode()
    return raw


def synthesize_silence(out_path: Path, duration_ms: int) -> None:
    n = int(SAMPLE_RATE * duration_ms / 1000)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * n)


def synthesize_tts(api_key: str, text: str, voice: str, language: str, out_path: Path) -> float:
    """Inworld TTS sync REST. Returns wall-clock ms."""
    body = {
        "text": text,
        "voiceId": voice,
        "modelId": TTS_MODEL,
        "audioConfig": {
            "audioEncoding": "LINEAR16",
            "sampleRateHertz": SAMPLE_RATE,
        },
        "applyTextNormalization": "ON",
    }
    req = urllib.request.Request(
        INWORLD_TTS_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read())
    elapsed_ms = (time.perf_counter() - t0) * 1000
    audio_b64 = payload.get("audioContent") or payload.get("result", {}).get("audioContent")
    if not audio_b64:
        raise RuntimeError(f"TTS response missing audioContent: keys={list(payload.keys())}")
    audio_bytes = base64.b64decode(audio_b64)
    # Inworld returns a complete WAV (RIFF header) when audioEncoding=LINEAR16 — write as-is.
    out_path.write_bytes(audio_bytes)
    return elapsed_ms


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as r:
        if r.getframerate() != SAMPLE_RATE:
            raise RuntimeError(f"{path} sample rate {r.getframerate()} != {SAMPLE_RATE}")
        if r.getsampwidth() != 2:
            raise RuntimeError(f"{path} sample width {r.getsampwidth()} != 2")
        return r.readframes(r.getnframes())


async def stream_stt(api_key: str, wav_path: Path, language: str) -> tuple[str, float, float, float]:
    """Stream WAV PCM to Inworld STT (Soniox v4 RT).

    Returns (final_transcript, last_final_after_audio_ms, first_interim_after_start_ms,
    first_final_after_start_ms).

    Protocol from shared/WaiSayKit/Sources/WaiSayKit/Network/InworldProviderSession.swift:
      send: transcribe_config -> N x audio_chunk -> end_turn -> close_stream
      recv: {transcription:{text, is_final, language}}, {usage:{...}}, {error:{...}}
    """
    pcm = read_pcm(wav_path)
    chunk_bytes = SAMPLE_RATE * 2 * CHUNK_MS // 1000
    final_segments: list[str] = []
    end_of_audio_ts: float | None = None
    last_final_ts: float | None = None
    first_interim_ts: float | None = None
    first_final_ts: float | None = None
    session_start_ts = time.perf_counter()

    async with websockets.connect(
        INWORLD_STT_WS,
        additional_headers={"Authorization": f"Basic {api_key}"},
        max_size=2**22,
    ) as ws:
        await ws.send(json.dumps({
            "transcribe_config": {
                "model_id": STT_MODEL,
                "language": language,
                "audio_encoding": "LINEAR16",
                "sample_rate_hertz": SAMPLE_RATE,
                "number_of_channels": 1,
            }
        }))

        # Inworld validation: chunk duration must be 20..1000ms. We pad the final
        # short chunk with silence so the server accepts it; alternative would
        # be to drop it but that loses audio at the boundary.
        min_chunk_bytes = SAMPLE_RATE * 2 * 20 // 1000  # 20ms

        async def sender() -> None:
            for i in range(0, len(pcm), chunk_bytes):
                chunk = pcm[i : i + chunk_bytes]
                if len(chunk) < min_chunk_bytes:
                    chunk = chunk + b"\x00" * (min_chunk_bytes - len(chunk))
                await ws.send(json.dumps({"audio_chunk": {"content": base64.b64encode(chunk).decode()}}))
                await asyncio.sleep(CHUNK_MS / 1000)
            nonlocal end_of_audio_ts
            end_of_audio_ts = time.perf_counter()
            await ws.send(json.dumps({"end_turn": {}}))
            await ws.send(json.dumps({"close_stream": {}}))

        send_task = asyncio.create_task(sender())

        trace = os.environ.get("NIGHTLY_TRACE") == "1"
        usage_seen = False
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
                if trace:
                    logger.info("STT frame: %s", raw[:400])
                msg = json.loads(raw)
                inner = msg.get("result") if isinstance(msg.get("result"), dict) else msg
                tx = inner.get("transcription") if isinstance(inner, dict) else None
                if tx:
                    text_raw = tx.get("transcript") or tx.get("text") or ""
                    is_final = tx.get("isFinal") or tx.get("is_final") or False
                    if text_raw.strip() and first_interim_ts is None:
                        first_interim_ts = time.perf_counter()
                    if is_final and text_raw.strip():
                        # Preserve raw text — merge_finals() needs leading/trailing
                        # whitespace as a boundary signal.
                        final_segments.append(text_raw)
                        if first_final_ts is None:
                            first_final_ts = time.perf_counter()
                        last_final_ts = time.perf_counter()
                    elif not is_final and text_raw.strip() and trace:
                        logger.info("STT interim: %r", text_raw)
                if (inner.get("usage") if isinstance(inner, dict) else None) is not None:
                    usage_seen = True
                err = (inner.get("error") if isinstance(inner, dict) else None) or msg.get("error")
                if err:
                    raise RuntimeError(f"inworld error frame: {err}")
                # Server emits usage as the last frame; close to avoid 15s recv timeout.
                if usage_seen:
                    break
        except asyncio.TimeoutError:
            pass
        except websockets.ConnectionClosedOK:
            pass
        except websockets.ConnectionClosed:
            pass
        finally:
            send_task.cancel()
            try:
                await send_task
            except (asyncio.CancelledError, Exception):
                pass

    e2e_ms = 0.0
    if end_of_audio_ts and last_final_ts:
        e2e_ms = max(0.0, (last_final_ts - end_of_audio_ts) * 1000)
    first_interim_ms = (
        max(0.0, (first_interim_ts - session_start_ts) * 1000)
        if first_interim_ts is not None else 0.0
    )
    first_final_ms = (
        max(0.0, (first_final_ts - session_start_ts) * 1000)
        if first_final_ts is not None else 0.0
    )
    return merge_finals(final_segments), e2e_ms, first_interim_ms, first_final_ms


async def run_scenario(
    api_key: str, scenario: dict[str, Any], run_dir: Path
) -> ScenarioResult:
    sid = scenario["id"]
    audio_path = run_dir / "audio" / f"{sid}.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    transcripts_path = run_dir / "transcripts" / f"{sid}.json"
    transcripts_path.parent.mkdir(parents=True, exist_ok=True)

    notes: list[str] = []
    tts_ms = 0.0
    if scenario.get("synthesize_silence_ms"):
        synthesize_silence(audio_path, scenario["synthesize_silence_ms"])
        notes.append(f"silence {scenario['synthesize_silence_ms']}ms")
    else:
        try:
            tts_ms = synthesize_tts(
                api_key,
                scenario["text"],
                scenario["voice"],
                scenario["language"],
                audio_path,
            )
        except Exception as e:
            return ScenarioResult(
                id=sid,
                category=scenario["category"],
                language=scenario["language"],
                voice=scenario["voice"],
                expected=scenario["text"],
                transcript="",
                wer=1.0,
                e2e_latency_ms=0.0,
                tts_ms=0.0,
                stt_ms=0.0,
                status="ERROR_TTS",
                notes=[f"tts failed: {e}"],
            )

    stt_t0 = time.perf_counter()
    try:
        transcript, e2e_ms, first_interim_ms, first_final_ms = await stream_stt(
            api_key, audio_path, scenario["language"]
        )
    except Exception as e:
        return ScenarioResult(
            id=sid,
            category=scenario["category"],
            language=scenario["language"],
            voice=scenario["voice"],
            expected=scenario["text"],
            transcript="",
            wer=1.0,
            e2e_latency_ms=0.0,
            tts_ms=tts_ms,
            stt_ms=0.0,
            status="ERROR_STT",
            notes=[f"stt failed: {e}"],
        )
    stt_ms = (time.perf_counter() - stt_t0) * 1000

    transcripts_path.write_text(
        json.dumps({"expected": scenario["text"], "transcript": transcript}, ensure_ascii=False, indent=2)
    )

    expect_empty = scenario.get("expect_empty_transcript")
    if expect_empty:
        wer_value = 0.0 if not transcript.strip() else 1.0
        status = "PASS" if wer_value == 0.0 else "FAIL_NONEMPTY_SILENCE"
    else:
        wer_value = wer(scenario["text"], transcript)
        status = "PASS"
        if wer_value > scenario["max_wer"]:
            status = "FAIL_WER"
            notes.append(f"WER {wer_value:.3f} > max {scenario['max_wer']:.3f}")
        if e2e_ms > scenario["max_latency_ms"]:
            status = "FAIL_LATENCY" if status == "PASS" else f"{status}+LATENCY"
            notes.append(f"E2E {e2e_ms:.0f}ms > max {scenario['max_latency_ms']}ms")

    cleaned_transcript = ""
    clean_wer_value = 0.0
    cleanup_ms = 0.0
    if scenario.get("apply_cleanup") and transcript:
        anthropic_key = load_anthropic_key()
        if anthropic_key is None:
            notes.append("cleanup_skipped_no_anthropic_key")
        else:
            try:
                cleaned_transcript, cleanup_ms = clean_with_anthropic(anthropic_key, transcript)
                cleaned_expected = scenario.get("cleaned_expected", scenario["text"])
                clean_wer_value = wer(cleaned_expected, cleaned_transcript)
                max_clean_wer = scenario.get("max_clean_wer", 0.20)
                if clean_wer_value > max_clean_wer:
                    status = "FAIL_CLEAN_WER" if status == "PASS" else f"{status}+CLEAN_WER"
                    notes.append(
                        f"clean WER {clean_wer_value:.3f} > max {max_clean_wer:.3f}"
                    )
            except Exception as e:
                notes.append(f"cleanup failed: {e}")
                status = "ERROR_CLEANUP" if status == "PASS" else f"{status}+CLEANUP"

    return ScenarioResult(
        id=sid,
        category=scenario["category"],
        language=scenario["language"],
        voice=scenario["voice"],
        expected=scenario["text"],
        transcript=transcript,
        wer=wer_value,
        e2e_latency_ms=e2e_ms,
        tts_ms=tts_ms,
        stt_ms=stt_ms,
        status=status,
        stt_first_interim_ms=first_interim_ms,
        stt_first_final_ms=first_final_ms,
        cleaned_transcript=cleaned_transcript,
        clean_wer=clean_wer_value,
        cleanup_ms=cleanup_ms,
        notes=notes,
    )


def aggregate_metrics(results: list[ScenarioResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.status == "PASS")
    by_cat: dict[str, dict[str, Any]] = {}
    for r in results:
        cat = by_cat.setdefault(r.category, {"total": 0, "passed": 0, "wers": [], "lats": []})
        cat["total"] += 1
        if r.status == "PASS":
            cat["passed"] += 1
        cat["wers"].append(r.wer)
        cat["lats"].append(r.e2e_latency_ms)
    wers = [r.wer for r in results if r.status != "ERROR_TTS" and r.status != "ERROR_STT"]
    lats = [r.e2e_latency_ms for r in results if r.e2e_latency_ms > 0]
    first_interims = [r.stt_first_interim_ms for r in results if r.stt_first_interim_ms > 0]
    first_finals = [r.stt_first_final_ms for r in results if r.stt_first_final_ms > 0]

    def _percentile(xs, p):
        if not xs:
            return None
        if len(xs) == 1:
            return xs[0]
        s = sorted(xs)
        return s[int(p * (len(s) - 1))]

    return {
        "total": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "wer_p50": statistics.median(wers) if wers else None,
        "wer_p95": _percentile(wers, 0.95),
        "latency_p50_ms": statistics.median(lats) if lats else None,
        "latency_p95_ms": _percentile(lats, 0.95),
        "first_interim_p50_ms": statistics.median(first_interims) if first_interims else None,
        "first_interim_p95_ms": _percentile(first_interims, 0.95),
        "first_final_p50_ms": statistics.median(first_finals) if first_finals else None,
        "first_final_p95_ms": _percentile(first_finals, 0.95),
        "by_category": {k: {**v, "wers": None, "lats": None,
                             "wer_p50": statistics.median(v["wers"]),
                             "lat_p50": statistics.median(v["lats"]) if v["lats"] else 0.0}
                        for k, v in by_cat.items()},
    }


def render_report(results: list[ScenarioResult], metrics: dict[str, Any], started_at: str) -> str:
    def _fmt(v, suffix=""):
        return f"{v:.0f}{suffix}" if v is not None else "n/a"

    lines = [
        "# WaiSay Nightly QA Report",
        "",
        f"- Started: {started_at}",
        f"- Total scenarios: {metrics['total']}",
        f"- Passed: {metrics['passed']} ({metrics['pass_rate']*100:.1f}%)",
        f"- WER p50: {metrics['wer_p50']:.3f}" if metrics["wer_p50"] is not None else "- WER p50: n/a",
        f"- WER p95: {metrics['wer_p95']:.3f}" if metrics["wer_p95"] is not None else "- WER p95: n/a",
        "",
        "### Latency",
        f"- **End-of-audio → last final — p50 {_fmt(metrics.get('latency_p50_ms'))} ms · p95 {_fmt(metrics.get('latency_p95_ms'))} ms** ← compare to Whispr Flow <250ms target.",
        f"- Session-start → first interim — p50 {_fmt(metrics.get('first_interim_p50_ms'))} ms · p95 {_fmt(metrics.get('first_interim_p95_ms'))} ms _(diagnostic; includes real-time-paced audio playback, so it's bounded below by audio length, not pure STT latency)_",
        f"- Session-start → first final — p50 {_fmt(metrics.get('first_final_p50_ms'))} ms · p95 {_fmt(metrics.get('first_final_p95_ms'))} ms _(diagnostic; same playback-time floor)_",
        "",
        "## Per scenario",
        "",
        "| ID | Cat | Lang | Voice | Status | WER | First-I ms | First-F ms | Last-F ms | Notes |",
        "|----|-----|------|-------|--------|-----|------------|------------|-----------|-------|",
    ]
    for r in results:
        notes = "; ".join(r.notes) if r.notes else ""
        lines.append(
            f"| `{r.id}` | {r.category} | {r.language} | {r.voice} | "
            f"{r.status} | {r.wer:.3f} | {r.stt_first_interim_ms:.0f} | "
            f"{r.stt_first_final_ms:.0f} | {r.e2e_latency_ms:.0f} | {notes} |"
        )
    cleanup_results = [r for r in results if r.cleanup_ms > 0 or r.clean_wer > 0 or r.category == "cleanup"]
    if cleanup_results:
        lines.extend([
            "",
            "## Cleanup tier (Tier 1.5 — Anthropic /cleanup post-processing)",
            "",
            "Mirrors backend/app/api/routes/dictation.py. Detects prompt drift by comparing",
            "post-cleanup text against `cleaned_expected`.",
            "",
            "| ID | Raw transcript | Cleaned | Clean WER | Cleanup ms |",
            "|----|----------------|---------|-----------|------------|",
        ])
        for r in cleanup_results:
            raw = r.transcript[:50] + ("…" if len(r.transcript) > 50 else "")
            cleaned = r.cleaned_transcript[:50] + ("…" if len(r.cleaned_transcript) > 50 else "")
            lines.append(
                f"| `{r.id}` | `{raw}` | `{cleaned}` | {r.clean_wer:.3f} | {r.cleanup_ms:.0f} |"
            )
    lines.extend(["", "## Per category", ""])
    for cat, c in metrics["by_category"].items():
        lines.append(
            f"- **{cat}**: {c['passed']}/{c['total']} pass · "
            f"WER p50 {c['wer_p50']:.3f} · lat p50 {c['lat_p50']:.0f}ms"
        )
    lines.append("")
    return "\n".join(lines)


async def main_async(scenarios_path: Path, artifacts_root: Path) -> int:
    api_key = load_inworld_key()
    scenarios = json.loads(scenarios_path.read_text())["scenarios"]

    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir = artifacts_root / "runs" / started_at
    run_dir.mkdir(parents=True, exist_ok=True)

    results: list[ScenarioResult] = []
    for scenario in scenarios:
        logger.info("scenario %s start", scenario["id"])
        try:
            r = await run_scenario(api_key, scenario, run_dir)
        except Exception as e:
            logger.exception("scenario %s crashed", scenario["id"])
            r = ScenarioResult(
                id=scenario["id"],
                category=scenario.get("category", "unknown"),
                language=scenario.get("language", "?"),
                voice=scenario.get("voice", "?"),
                expected=scenario.get("text", ""),
                transcript="",
                wer=1.0,
                e2e_latency_ms=0.0,
                tts_ms=0.0,
                stt_ms=0.0,
                status="CRASH",
                notes=[str(e)],
            )
        results.append(r)
        logger.info(
            "scenario %s status=%s wer=%.3f e2e=%.0fms",
            r.id, r.status, r.wer, r.e2e_latency_ms,
        )

    metrics = aggregate_metrics(results)
    metrics["started_at"] = started_at

    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    (run_dir / "results.json").write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2)
    )

    report_md = render_report(results, metrics, started_at)
    (run_dir / "report.md").write_text(report_md)
    (artifacts_root / "last-report.md").write_text(report_md)
    (artifacts_root / "last-report.json").write_text(
        json.dumps({"metrics": metrics, "results": [asdict(r) for r in results]},
                   ensure_ascii=False, indent=2, default=str)
    )

    return 0 if metrics["passed"] == metrics["total"] else 1


def self_test() -> int:
    """Lightweight assertion-based unit tests for pure helpers. No external IO."""
    cases_wer = [
        (("hello world", "hello world"), 0.0),
        (("hello world", "hello"), 0.5),
        (("", ""), 0.0),
        (("", "anything"), 1.0),
        (("a b c", "a x c"), 1 / 3),
    ]
    for (ref, hyp), expected in cases_wer:
        got = wer(ref, hyp)
        assert abs(got - expected) < 1e-6, f"wer({ref!r},{hyp!r})={got} expected {expected}"

    cases_merge = [
        ([], ""),
        ([""], ""),
        (["Open the recording from yesterday."], "Open the recording from yesterday."),
        # Empirically observed real Inworld pattern: previous final ends mid-utterance,
        # next final starts with a LEADING SPACE meaning "new word boundary".
        (["When we were planning the next quarter we", " agreed on three top priorities"],
         "When we were planning the next quarter we agreed on three top priorities"),
        # Mid-word fragmentation (also observed): "qu" + "arter" with no leading space.
        (["When we were planning the next qu", "arter, we agreed"],
         "When we were planning the next quarter, we agreed"),
        # Punctuation attaches left without a space, even with leading-ws absent.
        (["Third", ", we want to onboard"], "Third, we want to onboard"),
        # Two complete utterances separated by a leading-space signal.
        (["controls.", " Second, we need"], "controls. Second, we need"),
        # Mid-word continuation of "controls" into "s. Second" (no leading space).
        (["control", "s. Second, we need"], "controls. Second, we need"),
        # Empty middle segment skipped without affecting boundary detection.
        (["alpha", "", " beta"], "alpha beta"),
        # Leading-space wins over alnum-alnum heuristic.
        (["hello", " world"], "hello world"),
        # Whitespace-only segment treated as empty.
        (["foo", "   ", " bar"], "foo bar"),
    ]
    for inputs, expected in cases_merge:
        got = merge_finals(inputs)
        assert got == expected, f"merge_finals({inputs!r})={got!r} expected {expected!r}"

    print("self-test PASS:", len(cases_wer), "wer +", len(cases_merge), "merge_finals cases")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", default=str(Path(__file__).parent / "scenarios.json"))
    parser.add_argument("--artifacts", default=str(Path(__file__).parent / ".artifacts"))
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--self-test", action="store_true",
                        help="Run inline assertion tests for pure helpers and exit.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.self_test:
        return self_test()

    return asyncio.run(main_async(Path(args.scenarios), Path(args.artifacts)))


if __name__ == "__main__":
    sys.exit(main())
