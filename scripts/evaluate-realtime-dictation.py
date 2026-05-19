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
from urllib.parse import urlencode

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


DEFAULT_CANDIDATES = (
    ModelCandidate("elevenlabs", "scribe_v2_realtime"),
    ModelCandidate("soniox", "stt-rt-v4"),
    ModelCandidate("deepgram", "flux-general-multi"),
    ModelCandidate("inworld", "inworld/inworld-stt-1"),
)


def require_command(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"Required command not found: {name}")
    return path


def ensure_fixture(path: Path) -> bytes:
    if path.exists():
        return wav_pcm(path)

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
    response = await client.post("/api/auth/register", json={"email": email, "password": password})
    response.raise_for_status()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def patch_model(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    candidate: ModelCandidate,
) -> None:
    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={
            "dictation_live_stt_provider": candidate.provider,
            "dictation_live_stt_model": candidate.model,
        },
    )
    response.raise_for_status()


async def timed_settings(client: httpx.AsyncClient, headers: dict[str, str]) -> tuple[dict[str, Any], int]:
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


def elevenlabs_url(config: dict[str, Any]) -> str:
    query = {
        "model_id": config["model"],
        "token": config["token"],
        "include_timestamps": "true",
        "audio_format": "pcm_16000",
    }
    if config.get("language") in {"", "multi", "auto", "und"}:
        query["include_language_detection"] = "true"
    else:
        query["language_code"] = config["language"]
    if config.get("commit_strategy"):
        query["commit_strategy"] = config["commit_strategy"]
    if config.get("no_verbatim"):
        query["no_verbatim"] = "true"
    return f"wss://api.elevenlabs.io/v1/speech-to-text/realtime?{urlencode(query)}"


def websocket_target(config: dict[str, Any]) -> tuple[str, dict[str, str]]:
    provider = config["provider"]
    if provider == "elevenlabs":
        return elevenlabs_url(config), {}
    url = config.get("websocket_url")
    if not url:
        raise RuntimeError(f"{provider} config did not include websocket_url")
    headers: dict[str, str] = {}
    if config.get("auth_scheme") == "bearer":
        headers["Authorization"] = f"Bearer {config['token']}"
    elif config.get("auth_scheme") == "basic":
        headers["Authorization"] = str(config["token"])
    elif config.get("auth_scheme") in {"message_api_key", None, "query_token"}:
        pass
    else:
        raise RuntimeError(f"Unsupported auth_scheme={config.get('auth_scheme')}")
    return url, headers


def soniox_config(config: dict[str, Any]) -> str:
    language = str(config.get("language") or "multi").strip().lower()
    auto = language in {"", "multi", "auto", "und"}
    payload: dict[str, Any] = {
        "api_key": config["token"],
        "model": config["model"],
        "audio_format": "pcm_s16le",
        "sample_rate": config["sample_rate"],
        "num_channels": config["channels"],
        "enable_speaker_diarization": True,
        "enable_language_identification": auto,
        "enable_endpoint_detection": True,
        "max_endpoint_delay_ms": 500,
    }
    if not auto:
        payload["language_hints"] = [language]
    return json.dumps(payload)


def inworld_config(config: dict[str, Any]) -> str:
    language = str(config.get("language") or "").strip().lower()
    if language in {"multi", "und", "auto"}:
        language = ""
    if "-" in language:
        language = language.split("-", 1)[0]
    return json.dumps(
        {
            "transcribeConfig": {
                "modelId": config["model"],
                "language": language,
                "audioEncoding": "LINEAR16",
                "sampleRateHertz": config["sample_rate"],
                "numberOfChannels": config["channels"],
                "inactivityTimeoutSeconds": 60,
            }
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

    if provider == "elevenlabs":
        message_type = payload.get("message_type") or payload.get("type")
        if message_type == "partial_transcript":
            return cleaned(payload.get("text")), False
        if message_type in {"committed_transcript", "committed_transcript_with_timestamps"}:
            text = cleaned(payload.get("text"))
            if text:
                return text, True
            words = payload.get("words") or []
            return cleaned("".join(word.get("text", "") for word in words if word.get("type") != "spacing")), True
        return None, False

    if provider == "deepgram":
        if payload.get("type") == "Results":
            alternatives = ((payload.get("channel") or {}).get("alternatives") or [])
            text = cleaned((alternatives[0] if alternatives else {}).get("transcript"))
            return text, bool(payload.get("is_final") or payload.get("speech_final"))
        if payload.get("type") == "TurnInfo":
            return cleaned(payload.get("transcript")), payload.get("event") == "EndOfTurn"
        return cleaned(payload.get("transcript")), True

    if provider == "soniox":
        tokens = payload.get("tokens") or []
        final = [token for token in tokens if token.get("is_final") is True]
        non_final = [token for token in tokens if token.get("is_final") is not True]
        if final:
            return soniox_text(final), True
        if non_final:
            return soniox_text(non_final), False
        return None, False

    if provider == "inworld":
        transcription = payload.get("transcription")
        if not isinstance(transcription, dict):
            result = payload.get("result")
            if isinstance(result, dict):
                transcription = result.get("transcription")
        if isinstance(transcription, dict):
            return cleaned(transcription.get("text") or transcription.get("transcript")), bool(
                transcription.get("is_final") or transcription.get("isFinal")
            )
    return None, False


def cleaned(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    return value or None


def soniox_text(tokens: list[dict[str, Any]]) -> str | None:
    text = "".join(
        str(token.get("text") or "")
        for token in tokens
        if not str(token.get("text") or "").startswith("<")
        and token.get("translation_status") != "translation"
    )
    return cleaned(text)


async def stream_provider(config: dict[str, Any], pcm: bytes, press_started: float) -> dict[str, Any]:
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

    async with websockets.connect(url, additional_headers=headers or None, max_size=8 * 1024 * 1024) as ws:
        connect_ms = elapsed_ms(connect_started)
        if provider == "soniox":
            await ws.send(soniox_config(config))
        elif provider == "inworld":
            await ws.send(inworld_config(config))

        async def send_loop() -> None:
            for chunk in chunks(pcm):
                if provider == "elevenlabs":
                    await ws.send(
                        json.dumps(
                            {
                                "message_type": "input_audio_chunk",
                                "audio_base_64": base64.b64encode(chunk).decode(),
                                "sample_rate": SAMPLE_RATE,
                                "commit": False,
                            }
                        )
                    )
                elif provider == "inworld":
                    await ws.send(json.dumps({"audioChunk": {"content": base64.b64encode(chunk).decode()}}))
                else:
                    await ws.send(chunk)
                await asyncio.sleep(CHUNK_MS / 1000)

            if provider == "elevenlabs":
                await ws.send(
                    json.dumps(
                        {
                            "message_type": "input_audio_chunk",
                            "audio_base_64": base64.b64encode(b"\x00" * 640).decode(),
                            "sample_rate": SAMPLE_RATE,
                            "commit": True,
                        }
                    )
                )
            elif provider == "deepgram":
                await ws.send(silence())
                await ws.send(json.dumps({"type": "CloseStream"}))
            elif provider == "soniox":
                await ws.send(silence())
                await ws.send(json.dumps({"type": "finalize"}))
                await ws.send("")
            elif provider == "inworld":
                await ws.send(json.dumps({"endTurn": {}}))
                await ws.send(json.dumps({"closeStream": {}}))

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
    await patch_model(client, headers, candidate)
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
        "speed_factor": round(audio_seconds / (stream["final_ms"] / 1000), 2) if stream["final_ms"] else None,
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
                "median_first_text_ms": median(row["first_text_ms"] for row in rows if row["first_text_ms"] is not None),
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
    parser.add_argument("--output", default=str(ROOT / "artifacts/benchmarks/realtime-dictation-eval.json"))
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
                    print(json.dumps({k: v for k, v in result.items() if k != "transcript"}, ensure_ascii=False), flush=True)

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
