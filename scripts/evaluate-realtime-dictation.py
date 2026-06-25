#!/usr/bin/env python3
"""Measure WaiComputer realtime dictation startup/finalization on production.

The script registers an isolated temporary account, switches its dictation
model, mints a client-safe realtime session through the production API, then
connects to the returned backend realtime WebSocket and streams the same synthetic audio.
It reports cold-start and prefetched-start timings without printing secrets.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import shutil
import subprocess
import sys
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_TEXT_RU = (
    "Сегодня мы проверяем быстрый старт диктовки WaiComputer. "
    "Нужно распознать начало, середину и обязательно последнюю фразу."
)
FIXTURE_VOICE_RU = "Milena"
EXPECTED_TAIL = "последнюю фразу"
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
CHUNK_MS = 100
FINAL_SILENCE_MS = 240


@dataclass(frozen=True)
class ModelCandidate:
    provider: str
    model: str

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class ProviderMessage:
    text: str | None
    is_final: bool
    finalization_marker: bool
    speech_started: bool = False


DEFAULT_CANDIDATES = (
    ModelCandidate("deepgram", "nova-3"),
)
GATE_THRESHOLDS = {
    "prefetched": {
        "p95_first_text_ms": 1_000,
        "p95_wer": 0.08,
        "p95_cer": 0.04,
    },
    "cold": {
        "p95_first_text_ms": 1_300,
        "p95_wer": 0.08,
        "p95_cer": 0.04,
    },
}
LEGAL_ACCEPTANCE = {
    "accepted_legal_terms": True,
    "legal_terms_version": "2026-05-22",
    "legal_privacy_version": "2026-05-22",
}


def require_command(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"Required command not found: {name}")
    return path


def ensure_fixture(path: Path) -> bytes:
    if path.exists():
        try:
            return wav_pcm(path)
        except RuntimeError:
            path.unlink()

    require_command("say")
    require_command("afconvert")
    path.parent.mkdir(parents=True, exist_ok=True)
    aiff = path.with_suffix(".aiff")
    subprocess.run(
        ["say", "-v", FIXTURE_VOICE_RU, "-o", str(aiff), FIXTURE_TEXT_RU],
        check=True,
    )
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", str(aiff), str(path)],
        check=True,
    )
    aiff.unlink(missing_ok=True)
    return wav_pcm(path)


def wav_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != SAMPLE_RATE or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise RuntimeError(f"Fixture must be 16 kHz mono int16 WAV: {path}")
        return wav.readframes(wav.getnframes())


def duration_seconds(pcm: bytes) -> float:
    return len(pcm) / (SAMPLE_RATE * BYTES_PER_SAMPLE)


def chunks(pcm: bytes) -> list[bytes]:
    chunk_bytes = SAMPLE_RATE * BYTES_PER_SAMPLE * CHUNK_MS // 1000
    return [pcm[index : index + chunk_bytes] for index in range(0, len(pcm), chunk_bytes)]


def startup_buffered_chunk_count(elapsed_before_stream_ms: int, *, total_chunks: int) -> int:
    if elapsed_before_stream_ms <= 0 or total_chunks <= 0:
        return 0
    return min(total_chunks, elapsed_before_stream_ms // CHUNK_MS)


def silence(ms: int = FINAL_SILENCE_MS) -> bytes:
    return b"\x00" * (SAMPLE_RATE * BYTES_PER_SAMPLE * ms // 1000)


def normalize(text: str) -> str:
    chars = [char.casefold() if char.isalnum() or char.isspace() else " " for char in text]
    return " ".join("".join(chars).split())


def normalized_words(text: str) -> list[str]:
    normalized = normalize(text)
    return normalized.split() if normalized else []


def normalized_chars(text: str) -> list[str]:
    return list(normalize(text).replace(" ", ""))


def edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_value in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_value in enumerate(right, start=1):
            substitution = previous[right_index - 1] + (0 if left_value == right_value else 1)
            insertion = current[right_index - 1] + 1
            deletion = previous[right_index] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def error_rate(reference: list[str], hypothesis: list[str]) -> float | None:
    if not reference:
        return None
    return round(edit_distance(reference, hypothesis) / len(reference), 4)


def transcript_ok(text: str) -> bool:
    normalized = normalize(text)
    return normalize(EXPECTED_TAIL) in normalized


def transcript_metrics(text: str) -> dict[str, float | None]:
    return {
        "wer": error_rate(normalized_words(FIXTURE_TEXT_RU), normalized_words(text)),
        "cer": error_rate(normalized_chars(FIXTURE_TEXT_RU), normalized_chars(text)),
    }


async def register_user(client: httpx.AsyncClient) -> dict[str, str]:
    email = f"dictation-eval-{uuid.uuid4().hex[:12]}@example.com"
    password = f"eval-{uuid.uuid4().hex}"
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, **LEGAL_ACCEPTANCE},
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def assert_model(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    candidate: ModelCandidate,
) -> None:
    response = await client.get("/api/settings", headers=headers)
    response.raise_for_status()
    settings = response.json()
    actual = (
        settings.get("dictation_live_stt_provider"),
        settings.get("dictation_live_stt_model"),
    )
    expected = (candidate.provider, candidate.model)
    if actual != expected:
        raise RuntimeError(
            f"Production dictation model is {actual[0]}/{actual[1]}, "
            f"expected {expected[0]}/{expected[1]}."
        )


async def timed_settings(
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> tuple[dict[str, Any], int]:
    start = time.perf_counter()
    response = await client.get("/api/settings", headers=headers)
    response.raise_for_status()
    return response.json(), elapsed_ms(start)


async def timed_mint(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    language: str,
) -> tuple[dict[str, Any], int]:
    start = time.perf_counter()
    response = await client.post(
        "/api/transcription/session",
        headers=headers,
        json={"language": language, "channels": 1, "purpose": "dictation"},
    )
    response.raise_for_status()
    return response.json(), elapsed_ms(start)


def elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def websocket_target(config: dict[str, Any]) -> tuple[str, dict[str, str]]:
    provider = config["provider"]
    if provider != "deepgram":
        raise RuntimeError(f"Unsupported realtime provider from backend: {provider}")
    url = config.get("websocket_url")
    if not url:
        raise RuntimeError(f"{provider} config did not include websocket_url")
    if config.get("auth_scheme") != "bearer":
        raise RuntimeError(f"Unsupported auth_scheme={config.get('auth_scheme')}")
    return url, {"Authorization": f"Bearer {config['token']}"}


def parse_message(provider: str, raw: str | bytes) -> ProviderMessage:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return ProviderMessage(None, False, False)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ProviderMessage(None, False, False)

    if provider == "deepgram":
        message_type = payload.get("type")
        if message_type == "Results":
            alternatives = payload.get("channel", {}).get("alternatives", [])
            alternative = alternatives[0] if alternatives else {}
            is_final = bool(payload.get("is_final"))
            from_finalize = bool(payload.get("from_finalize"))
            return ProviderMessage(cleaned(alternative.get("transcript")), is_final, from_finalize)
        if message_type == "SpeechStarted":
            return ProviderMessage(None, False, False, speech_started=True)
        if message_type == "Metadata":
            return ProviderMessage(None, False, True)
        if message_type in {"Error", "error"}:
            raise RuntimeError(
                payload.get("message")
                or payload.get("description")
                or payload.get("reason")
                or "Deepgram realtime error"
            )
    return ProviderMessage(None, False, False)


def cleaned(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    return value or None


async def stream_provider(
    config: dict[str, Any],
    pcm: bytes,
    press_started: float,
) -> dict[str, Any]:
    provider = config["provider"]
    url, headers = websocket_target(config)
    connect_started = time.perf_counter()
    final_segments: list[str] = []
    partial_text = ""
    first_speech_ms: int | None = None
    first_text_ms: int | None = None
    first_final_ms: int | None = None
    send_done = asyncio.Event()
    finalization_marker_received = False

    def append_final(text: str) -> None:
        if final_segments and normalize(final_segments[-1]) == normalize(text):
            return
        final_segments.append(text)

    async with websockets.connect(url, additional_headers=headers, max_size=8 * 1024 * 1024) as ws:
        connect_ms = elapsed_ms(connect_started)
        audio_chunks = chunks(pcm)
        buffered_chunk_count = startup_buffered_chunk_count(
            elapsed_ms(press_started),
            total_chunks=len(audio_chunks),
        )

        async def keep_alive_loop() -> None:
            interval = int(config.get("keep_alive_interval_seconds") or 4)
            while True:
                await asyncio.sleep(max(interval, 1))
                await ws.send(json.dumps({"type": "KeepAlive"}))

        async def send_loop() -> None:
            try:
                for chunk in audio_chunks[:buffered_chunk_count]:
                    await ws.send(chunk)
                for chunk in audio_chunks[buffered_chunk_count:]:
                    await ws.send(chunk)
                    await asyncio.sleep(CHUNK_MS / 1000)
                await ws.send(silence())
                await ws.send(json.dumps({"type": "Finalize"}))
            finally:
                send_done.set()

        async def receive_loop() -> None:
            nonlocal first_speech_ms, first_text_ms, first_final_ms, partial_text
            nonlocal finalization_marker_received
            while True:
                try:
                    timeout = 2.5 if send_done.is_set() else 8
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except (TimeoutError, ConnectionClosed):
                    return
                message = parse_message(provider, raw)
                if message.speech_started and first_speech_ms is None:
                    first_speech_ms = elapsed_ms(press_started)
                finalization_marker_received = (
                    finalization_marker_received or message.finalization_marker
                )
                if finalization_marker_received and not message.text:
                    return
                if not message.text:
                    continue
                if first_text_ms is None:
                    first_text_ms = elapsed_ms(press_started)
                if message.is_final:
                    append_final(message.text)
                    first_final_ms = first_final_ms or elapsed_ms(press_started)
                    if transcript_ok(" ".join(final_segments)):
                        return
                else:
                    partial_text = message.text

        keep_alive_task = asyncio.create_task(keep_alive_loop())
        send_task = asyncio.create_task(send_loop())
        receive_task = asyncio.create_task(receive_loop())
        await send_task
        try:
            await asyncio.wait_for(receive_task, timeout=8)
        except TimeoutError:
            receive_task.cancel()
            await asyncio.gather(receive_task, return_exceptions=True)
        finally:
            keep_alive_task.cancel()
            await asyncio.gather(keep_alive_task, return_exceptions=True)
            with contextlib.suppress(Exception):
                await ws.send(json.dumps({"type": "CloseStream"}))

    transcript = " ".join(final_segments).strip() or partial_text
    quality = transcript_metrics(transcript)
    return {
        "connect_ms": connect_ms,
        "startup_buffered_ms": buffered_chunk_count * CHUNK_MS,
        "startup_buffered_chunks": buffered_chunk_count,
        "first_speech_ms": first_speech_ms,
        "first_text_ms": first_text_ms,
        "first_final_ms": first_final_ms,
        "final_ms": elapsed_ms(press_started),
        "word_count": len(transcript.split()),
        "ok": transcript_ok(transcript),
        "wer": quality["wer"],
        "cer": quality["cer"],
        "transcript": transcript,
    }


async def run_one(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    candidate: ModelCandidate,
    pcm: bytes,
    language: str,
    mode: str,
) -> dict[str, Any]:
    await assert_model(client, headers, candidate)
    prefetch_ms: int | None = None
    prefetched_config: dict[str, Any] | None = None
    if mode == "prefetched":
        prefetch_started = time.perf_counter()
        _, _ = await timed_settings(client, headers)
        prefetched_config, _ = await timed_mint(client, headers, language)
        prefetch_ms = elapsed_ms(prefetch_started)

    press_started = time.perf_counter()
    settings_ms = 0
    mint_ms = 0
    if prefetched_config is None:
        _, settings_ms = await timed_settings(client, headers)
        config, mint_ms = await timed_mint(client, headers, language)
    else:
        config = prefetched_config

    stream = await stream_provider(config, pcm, press_started)
    audio_seconds = duration_seconds(pcm)
    return {
        "mode": mode,
        "provider": candidate.provider,
        "model": candidate.model,
        "settings_ms": settings_ms,
        "mint_ms": mint_ms,
        "prefetch_ms": prefetch_ms,
        "connect_ms": stream["connect_ms"],
        "startup_buffered_ms": stream["startup_buffered_ms"],
        "startup_buffered_chunks": stream["startup_buffered_chunks"],
        "first_speech_ms": stream["first_speech_ms"],
        "first_text_ms": stream["first_text_ms"],
        "first_final_ms": stream["first_final_ms"],
        "final_ms": stream["final_ms"],
        "speed_factor": (
            round(audio_seconds / (stream["final_ms"] / 1000), 2)
            if stream["final_ms"]
            else None
        ),
        "word_count": stream["word_count"],
        "ok": stream["ok"],
        "wer": stream["wer"],
        "cer": stream["cer"],
        "transcript": stream["transcript"],
    }


def summarize(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault((result["mode"], result["provider"], result["model"]), []).append(result)
    summaries = []
    for (mode, provider, model), rows in grouped.items():
        ok_rows = [row for row in rows if row.get("ok")]
        first_speech_values = metric_values(ok_rows, "first_speech_ms")
        first_text_values = metric_values(ok_rows, "first_text_ms")
        final_values = metric_values(ok_rows, "final_ms")
        connect_values = metric_values(ok_rows, "connect_ms")
        mint_values = metric_values(ok_rows, "mint_ms")
        wer_values = metric_values(ok_rows, "wer")
        cer_values = metric_values(ok_rows, "cer")
        summaries.append(
            {
                "mode": mode,
                "provider": provider,
                "model": model,
                "runs": len(rows),
                "ok_runs": len(ok_rows),
                "error_runs": len(rows) - len(ok_rows),
                "median_first_speech_ms": median(first_speech_values),
                "p95_first_speech_ms": percentile(first_speech_values),
                "median_first_text_ms": median(first_text_values),
                "p95_first_text_ms": percentile(first_text_values),
                "median_final_ms": median(final_values),
                "p95_final_ms": percentile(final_values),
                "median_connect_ms": median(connect_values),
                "p95_connect_ms": percentile(connect_values),
                "median_mint_ms": median(mint_values),
                "p95_mint_ms": percentile(mint_values),
                "median_wer": median_float(wer_values),
                "p95_wer": percentile_float(wer_values),
                "median_cer": median_float(cer_values),
                "p95_cer": percentile_float(cer_values),
            }
        )
    return sorted(
        summaries,
        key=lambda item: (
            item["mode"],
            -item["ok_runs"],
            item["median_first_text_ms"] if item["median_first_text_ms"] is not None else 999_999,
            item["median_final_ms"],
        ),
    )


def metric_values(rows: list[dict[str, Any]], metric: str) -> list[Any]:
    return [row[metric] for row in rows if row.get(metric) is not None]


def median(values_iter: Any) -> int | None:
    values = sorted(int(value) for value in values_iter if value is not None)
    if not values:
        return None
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return round((values[midpoint - 1] + values[midpoint]) / 2)


def median_float(values_iter: Any) -> float | None:
    values = sorted(float(value) for value in values_iter if value is not None)
    if not values:
        return None
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return round((values[midpoint - 1] + values[midpoint]) / 2, 4)


def percentile(values_iter: Any, percentile_value: int = 95) -> int | None:
    values = sorted(int(value) for value in values_iter if value is not None)
    if not values:
        return None
    index = max(0, min(len(values) - 1, math.ceil(len(values) * percentile_value / 100) - 1))
    return values[index]


def percentile_float(values_iter: Any, percentile_value: int = 95) -> float | None:
    values = sorted(float(value) for value in values_iter if value is not None)
    if not values:
        return None
    index = max(0, min(len(values) - 1, math.ceil(len(values) * percentile_value / 100) - 1))
    return round(values[index], 4)


def gate_summary(summary: dict[str, Any]) -> list[str]:
    label = f"{summary['mode']} {summary['provider']}:{summary['model']}"
    failures: list[str] = []
    error_runs = int(summary.get("error_runs") or 0)
    if error_runs:
        failures.append(f"{label} had {error_runs} error runs")

    thresholds = GATE_THRESHOLDS.get(summary["mode"], {})
    for metric, threshold in thresholds.items():
        actual = summary.get(metric)
        if actual is None or actual <= threshold:
            continue
        suffix = "ms" if metric.endswith("_ms") else ""
        failures.append(f"{label} {metric}={actual}{suffix} > {threshold}{suffix}")
    return failures


async def async_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://wai.computer")
    parser.add_argument("--language", default="ru")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--output",
        default=str(ROOT / "artifacts/benchmarks/realtime-dictation-eval.json"),
    )
    parser.add_argument("--fixture", default=str(ROOT / ".tmp/dictation-eval/ru-startup.wav"))
    parser.add_argument("--enforce-gates", action="store_true")
    args = parser.parse_args()

    pcm = ensure_fixture(Path(args.fixture))
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30.0) as client:
        headers = await register_user(client)
        for mode in ("cold", "prefetched"):
            for candidate in DEFAULT_CANDIDATES:
                for run_index in range(args.runs):
                    print(f"run mode={mode} model={candidate.id} idx={run_index + 1}", flush=True)
                    try:
                        result = await run_one(client, headers, candidate, pcm, args.language, mode)
                    except Exception as exc:
                        result = {
                            "mode": mode,
                            "provider": candidate.provider,
                            "model": candidate.model,
                            "ok": False,
                            "error": str(exc),
                        }
                    results.append(result)
                    printable_result = {k: v for k, v in result.items() if k != "transcript"}
                    print(json.dumps(printable_result, ensure_ascii=False), flush=True)

    summary = summarize(results)
    gate_failures = [failure for item in summary for failure in gate_summary(item)]
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": args.base_url,
        "fixture_text": FIXTURE_TEXT_RU,
        "fixture_seconds": round(duration_seconds(pcm), 3),
        "summary": summary,
        "gate_failures": gate_failures,
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    if gate_failures:
        print("gate failures:", flush=True)
        for failure in gate_failures:
            print(f"- {failure}", flush=True)
        if args.enforce_gates:
            raise SystemExit(1)


if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(130)
