#!/usr/bin/env python3
"""Measure WaiComputer realtime dictation startup/finalization on production.

The script registers an isolated temporary account, switches its dictation
model, mints a client-safe realtime session through the production API, then
connects to the actual provider WebSocket and streams the same synthetic audio.
It reports cold-start and prefetched-start timings without printing secrets.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
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
SAMPLE_RATE = 24_000
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


DEFAULT_CANDIDATES = (
    ModelCandidate("openai", "gpt-realtime-whisper"),
)
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
    if provider != "openai":
        raise RuntimeError(f"Unsupported realtime provider from backend: {provider}")
    url = config.get("websocket_url")
    if not url:
        raise RuntimeError(f"{provider} config did not include websocket_url")
    if config.get("auth_scheme") != "bearer":
        raise RuntimeError(f"Unsupported auth_scheme={config.get('auth_scheme')}")
    return url, {"Authorization": f"Bearer {config['token']}"}


def openai_session_update(config: dict[str, Any]) -> str:
    transcription: dict[str, Any] = {"model": config["model"]}
    language = str(config.get("language") or "multi").strip().lower()
    if language not in {"", "multi", "auto", "und"}:
        transcription["language"] = language.split("-", 1)[0]

    return json.dumps(
        {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {
                            "type": "audio/pcm",
                            "rate": config["sample_rate"],
                        },
                        "transcription": transcription,
                        "turn_detection": None,
                    }
                },
            },
        }
    )


def parse_message(provider: str, raw: str | bytes) -> tuple[str | None, bool]:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, False

    if provider == "openai":
        message_type = payload.get("type")
        if message_type == "conversation.item.input_audio_transcription.delta":
            return cleaned(payload.get("delta")), False
        if message_type == "conversation.item.input_audio_transcription.completed":
            return cleaned(payload.get("transcript")), True
        if message_type == "error":
            error = payload.get("error")
            if isinstance(error, dict):
                raise RuntimeError(
                    error.get("message") or error.get("code") or "OpenAI realtime error"
                )
    return None, False


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
    first_text_ms: int | None = None
    first_final_ms: int | None = None

    def append_final(text: str) -> None:
        if final_segments and normalize(final_segments[-1]) == normalize(text):
            return
        final_segments.append(text)

    async with websockets.connect(url, additional_headers=headers, max_size=8 * 1024 * 1024) as ws:
        connect_ms = elapsed_ms(connect_started)
        await ws.send(openai_session_update(config))

        async def send_loop() -> None:
            uncommitted_bytes = 0
            commit_threshold = (
                int(config["sample_rate"]) * max(int(config["channels"]), 1) * BYTES_PER_SAMPLE
            )
            for chunk in chunks(pcm):
                await ws.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode(),
                        }
                    )
                )
                uncommitted_bytes += len(chunk)
                if uncommitted_bytes >= commit_threshold:
                    await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    uncommitted_bytes = 0
                await asyncio.sleep(CHUNK_MS / 1000)

            tail = silence()
            await ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(tail).decode(),
                    }
                )
            )
            uncommitted_bytes += len(tail)
            if uncommitted_bytes > 0:
                await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

        async def receive_loop() -> None:
            nonlocal first_text_ms, first_final_ms, partial_text
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=8)
                except (TimeoutError, ConnectionClosed):
                    return
                text, is_final = parse_message(provider, raw)
                if not text:
                    continue
                if first_text_ms is None:
                    first_text_ms = elapsed_ms(press_started)
                if is_final:
                    append_final(text)
                    first_final_ms = first_final_ms or elapsed_ms(press_started)
                else:
                    partial_text = text

        send_task = asyncio.create_task(send_loop())
        receive_task = asyncio.create_task(receive_loop())
        await send_task
        try:
            await asyncio.wait_for(receive_task, timeout=8)
        except TimeoutError:
            receive_task.cancel()
            await asyncio.gather(receive_task, return_exceptions=True)

    transcript = " ".join(final_segments).strip() or partial_text
    quality = transcript_metrics(transcript)
    return {
        "connect_ms": connect_ms,
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
        summaries.append(
            {
                "mode": mode,
                "provider": provider,
                "model": model,
                "runs": len(rows),
                "ok_runs": sum(1 for row in rows if row["ok"]),
                "median_first_text_ms": median(
                    row["first_text_ms"] for row in rows if row["first_text_ms"] is not None
                ),
                "median_final_ms": median(row["final_ms"] for row in rows),
                "median_connect_ms": median(row["connect_ms"] for row in rows),
                "median_mint_ms": median(row["mint_ms"] for row in rows),
                "median_wer": median_float(row["wer"] for row in rows if row["wer"] is not None),
                "median_cer": median_float(row["cer"] for row in rows if row["cer"] is not None),
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


def median(values_iter: Any) -> int | None:
    values = sorted(int(value) for value in values_iter)
    if not values:
        return None
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return round((values[midpoint - 1] + values[midpoint]) / 2)


def median_float(values_iter: Any) -> float | None:
    values = sorted(float(value) for value in values_iter)
    if not values:
        return None
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return round((values[midpoint - 1] + values[midpoint]) / 2, 4)


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

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": args.base_url,
        "fixture_text": FIXTURE_TEXT_RU,
        "fixture_seconds": round(duration_seconds(pcm), 3),
        "summary": summarize([row for row in results if "error" not in row]),
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}")


if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(130)
