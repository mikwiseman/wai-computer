"""Server-side live dictation benchmark fan-out.

The browser streams one 16 kHz mono PCM feed to WaiComputer. The backend fans
that same audio out to selected realtime STT providers and normalizes their
partial/final events for the benchmark UI. Long-lived provider credentials stay
server-side.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import websockets
from websockets.exceptions import ConnectionClosed

from app.config import Settings, get_settings
from app.core.deepgram import DEEPGRAM_FLUX_REALTIME_WS_BASE
from app.core.soniox import SONIOX_REALTIME_WS_URL
from app.core.transcription_options import (
    TRANSCRIPTION_OPTIONS,
    ModelOption,
    provider_is_configured,
)

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
CHANNELS = 1
BYTES_PER_SAMPLE = 2
FINALIZATION_SILENCE_MS = 240
FINALIZATION_WAIT_SECONDS = 2.8
MAX_LIVE_BENCHMARK_MODELS = 3
SUPPORTED_LIVE_BENCHMARK_PROVIDERS = {"elevenlabs", "soniox", "deepgram"}


@dataclass(frozen=True)
class LiveBenchmarkModel:
    id: str
    provider: str
    model: str
    label: str


def configured_live_benchmark_models(
    *,
    settings: Settings | None = None,
) -> list[LiveBenchmarkModel]:
    """Return provider/model pairs supported by the live browser benchmark."""
    resolved_settings = settings or get_settings()
    models: list[LiveBenchmarkModel] = []
    for option in TRANSCRIPTION_OPTIONS["dictation_live_stt"]:
        if option.provider not in SUPPORTED_LIVE_BENCHMARK_PROVIDERS:
            continue
        if not provider_is_configured(option.provider, resolved_settings):
            continue
        models.append(_model_from_option(option))
        if len(models) >= MAX_LIVE_BENCHMARK_MODELS:
            break
    return models


def _model_from_option(option: ModelOption) -> LiveBenchmarkModel:
    return LiveBenchmarkModel(
        id=uuid4().hex,
        provider=option.provider,
        model=option.model,
        label=option.label,
    )


def _language_hints(language: str) -> list[str]:
    cleaned = (language or "").strip().lower()
    if not cleaned or cleaned in {"auto", "multi", "und"}:
        return []
    return [cleaned]


def _language_for_elevenlabs(language: str) -> list[tuple[str, str]]:
    hints = _language_hints(language)
    if hints:
        return [("language_code", hints[0])]
    return [("include_language_detection", "true")]


def _word_count(text: str) -> int:
    return len([word for word in text.split() if word.strip()])


def _normalise_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _silence_frame() -> bytes:
    sample_count = int(SAMPLE_RATE * (FINALIZATION_SILENCE_MS / 1000))
    return b"\x00" * sample_count * BYTES_PER_SAMPLE * CHANNELS


SendEvent = Callable[[dict[str, Any]], Awaitable[None]]


class LiveBenchmarkProviderRunner:
    """One upstream realtime STT connection inside a benchmark battle."""

    def __init__(
        self,
        *,
        battle_id: str,
        candidate: LiveBenchmarkModel,
        language: str,
        settings: Settings,
        send_event: SendEvent,
    ) -> None:
        self.battle_id = battle_id
        self.candidate = candidate
        self.language = language
        self.settings = settings
        self.send_event = send_event
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
        self.started_at = time.perf_counter()
        self.final_segments: list[str] = []
        self.partial_text = ""
        self.last_emitted_text = ""

    async def enqueue_audio(self, audio: bytes) -> None:
        await self.queue.put(audio)

    async def finish(self) -> None:
        await self.queue.put(None)

    async def run(self) -> None:
        await self._emit_status("running")
        try:
            if self.candidate.provider == "elevenlabs":
                await self._run_elevenlabs()
            elif self.candidate.provider == "soniox":
                await self._run_soniox()
            elif self.candidate.provider == "deepgram":
                await self._run_deepgram()
            else:
                raise RuntimeError(f"Unsupported live provider: {self.candidate.provider}")
            await self._emit_completion()
        except Exception as exc:
            logger.warning(
                "live dictation benchmark provider failed provider=%s model=%s error=%s",
                self.candidate.provider,
                self.candidate.model,
                exc,
            )
            await self._emit_error("Provider live stream failed.")

    async def _run_elevenlabs(self) -> None:
        if not self.settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not configured")

        query: list[tuple[str, str]] = [
            ("model_id", self.candidate.model),
            ("include_timestamps", "true"),
            ("audio_format", "pcm_16000"),
            ("commit_strategy", "vad"),
        ]
        query.extend(_language_for_elevenlabs(self.language))
        if self.settings.elevenlabs_no_verbatim:
            query.append(("no_verbatim", "true"))
        url = f"wss://api.elevenlabs.io/v1/speech-to-text/realtime?{urlencode(query)}"
        headers = {"xi-api-key": self.settings.elevenlabs_api_key}

        async with websockets.connect(url, additional_headers=headers) as upstream:
            await self._pump(upstream, self._send_elevenlabs_audio, self._handle_elevenlabs)

    async def _run_soniox(self) -> None:
        if not self.settings.soniox_api_key:
            raise RuntimeError("SONIOX_API_KEY not configured")

        async with websockets.connect(SONIOX_REALTIME_WS_URL) as upstream:
            await upstream.send(json.dumps(self._soniox_config()))
            await self._pump(upstream, self._send_soniox_audio, self._handle_soniox)

    async def _run_deepgram(self) -> None:
        if not self.settings.deepgram_api_key:
            raise RuntimeError("DEEPGRAM_API_KEY not configured")

        params: list[tuple[str, str]] = [
            ("model", self.candidate.model),
            ("encoding", "linear16"),
            ("sample_rate", str(SAMPLE_RATE)),
        ]
        for hint in _language_hints(self.language):
            params.append(("language_hint", hint))
        url = f"{DEEPGRAM_FLUX_REALTIME_WS_BASE}?{urlencode(params)}"
        headers = {"Authorization": f"Token {self.settings.deepgram_api_key}"}

        async with websockets.connect(url, additional_headers=headers) as upstream:
            await self._pump(upstream, self._send_deepgram_audio, self._handle_deepgram)

    async def _pump(
        self,
        upstream: Any,
        send_audio: Callable[[Any, bytes | None], Awaitable[None]],
        handle_message: Callable[[str], Awaitable[None]],
    ) -> None:
        send_task = asyncio.create_task(self._send_loop(upstream, send_audio))
        receive_task = asyncio.create_task(self._receive_loop(upstream, handle_message))
        try:
            done, pending = await asyncio.wait(
                {send_task, receive_task},
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in done:
                exception = task.exception()
                if exception is not None:
                    raise exception
            for task in pending:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        finally:
            send_task.cancel()
            receive_task.cancel()
            await asyncio.gather(send_task, receive_task, return_exceptions=True)

    async def _send_loop(
        self,
        upstream: Any,
        send_audio: Callable[[Any, bytes | None], Awaitable[None]],
    ) -> None:
        while True:
            chunk = await self.queue.get()
            await send_audio(upstream, chunk)
            if chunk is None:
                await asyncio.sleep(FINALIZATION_WAIT_SECONDS)
                await upstream.close()
                return

    async def _receive_loop(
        self,
        upstream: Any,
        handle_message: Callable[[str], Awaitable[None]],
    ) -> None:
        try:
            async for message in upstream:
                if isinstance(message, bytes):
                    try:
                        message = message.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                if isinstance(message, str):
                    await handle_message(message)
        except ConnectionClosed:
            return

    async def _send_elevenlabs_audio(self, upstream: Any, chunk: bytes | None) -> None:
        audio = _silence_frame() if chunk is None else chunk
        payload = {
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(audio).decode("ascii"),
            "sample_rate": SAMPLE_RATE,
            "commit": chunk is None,
        }
        await upstream.send(json.dumps(payload))

    async def _send_soniox_audio(self, upstream: Any, chunk: bytes | None) -> None:
        if chunk is None:
            await upstream.send(_silence_frame())
            await upstream.send(json.dumps({"type": "finalize"}))
            await asyncio.sleep(0.2)
            await upstream.send("")
            return
        await upstream.send(chunk)

    async def _send_deepgram_audio(self, upstream: Any, chunk: bytes | None) -> None:
        if chunk is None:
            await upstream.send(json.dumps({"type": "CloseStream"}))
            return
        await upstream.send(chunk)

    def _soniox_config(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "api_key": self.settings.soniox_api_key,
            "model": self.candidate.model,
            "audio_format": "pcm_s16le",
            "sample_rate": SAMPLE_RATE,
            "num_channels": CHANNELS,
            "enable_language_identification": not _language_hints(self.language),
            "enable_endpoint_detection": True,
            "max_endpoint_delay_ms": 500,
        }
        hints = _language_hints(self.language)
        if hints:
            payload["language_hints"] = hints
        return payload

    async def _handle_elevenlabs(self, text: str) -> None:
        payload = _json_object(text)
        if payload is None:
            return
        message_type = payload.get("message_type") or payload.get("type")
        if message_type == "partial_transcript":
            partial = str(payload.get("text") or "").strip()
            if partial:
                await self._emit_transcript(partial, final=False, append=False)
            return
        if message_type in {"committed_transcript", "committed_transcript_with_timestamps"}:
            transcript = str(payload.get("text") or "").strip()
            if transcript:
                await self._emit_transcript(transcript, final=True, append=True)
            return
        if isinstance(message_type, str) and (
            message_type == "error"
            or message_type.endswith("error")
            or "_error" in message_type
        ):
            raise RuntimeError(str(payload.get("message") or payload.get("error") or message_type))

    async def _handle_soniox(self, text: str) -> None:
        payload = _json_object(text)
        if payload is None:
            return
        if payload.get("error_code"):
            raise RuntimeError(str(payload.get("error_message") or payload["error_code"]))

        tokens = payload.get("tokens")
        if not isinstance(tokens, list):
            return
        final_text = _soniox_tokens_text(tokens, final=True)
        partial_text = _soniox_tokens_text(tokens, final=False)
        if final_text:
            await self._emit_transcript(final_text, final=True, append=True)
        if partial_text:
            await self._emit_transcript(partial_text, final=False, append=False)

    async def _handle_deepgram(self, text: str) -> None:
        payload = _json_object(text)
        if payload is None:
            return
        payload_type = payload.get("type")
        if payload_type in {"FatalError", "Error"}:
            raise RuntimeError(
                str(payload.get("description") or payload.get("message") or payload_type)
            )

        if payload_type == "TurnInfo":
            transcript = str(payload.get("transcript") or "").strip()
            if not transcript:
                return
            event = payload.get("event")
            await self._emit_transcript(
                transcript,
                final=event == "EndOfTurn",
                append=event == "EndOfTurn",
            )
            return

        if payload_type == "Results":
            channel = payload.get("channel")
            alternatives = channel.get("alternatives") if isinstance(channel, dict) else None
            top = alternatives[0] if isinstance(alternatives, list) and alternatives else None
            if not isinstance(top, dict):
                return
            transcript = str(top.get("transcript") or "").strip()
            if transcript:
                is_final = bool(payload.get("is_final") or payload.get("speech_final"))
                await self._emit_transcript(transcript, final=is_final, append=is_final)

    async def _emit_status(self, status_value: str) -> None:
        await self.send_event(
            {
                "type": "candidate_status",
                "battle_id": self.battle_id,
                "candidate": self._candidate_payload(status=status_value),
            }
        )

    async def _emit_error(self, message: str) -> None:
        await self.send_event(
            {
                "type": "candidate_error",
                "battle_id": self.battle_id,
                "candidate": self._candidate_payload(status="error", error=message),
            }
        )

    async def _emit_completion(self) -> None:
        if not self.last_emitted_text:
            await self._emit_error("No live transcript returned.")
            return
        await self.send_event(
            {
                "type": "candidate_update",
                "battle_id": self.battle_id,
                "is_final": True,
                "candidate": self._candidate_payload(status="ok"),
            }
        )

    async def _emit_transcript(self, text: str, *, final: bool, append: bool) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        if final and append:
            previous = _normalise_text(self.final_segments[-1]) if self.final_segments else None
            if previous != _normalise_text(cleaned):
                self.final_segments.append(cleaned)
            self.partial_text = ""
        else:
            self.partial_text = cleaned

        full_text = " ".join(
            self.final_segments + ([self.partial_text] if self.partial_text else [])
        )
        full_text = full_text.strip()
        if not full_text or full_text == self.last_emitted_text:
            return
        self.last_emitted_text = full_text

        await self.send_event(
            {
                "type": "candidate_update",
                "battle_id": self.battle_id,
                "is_final": final,
                "candidate": self._candidate_payload(
                    status="ok" if final else "running",
                    transcript=full_text,
                ),
            }
        )

    def _candidate_payload(
        self,
        *,
        status: str,
        transcript: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        resolved_text = transcript if transcript is not None else self.last_emitted_text or None
        return {
            "id": self.candidate.id,
            "provider": self.candidate.provider,
            "model": self.candidate.model,
            "label": self.candidate.label,
            "status": status,
            "transcript": resolved_text,
            "latency_ms": round((time.perf_counter() - self.started_at) * 1000),
            "word_count": _word_count(resolved_text or "") if resolved_text else 0,
            "error": error,
        }


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _soniox_tokens_text(tokens: list[Any], *, final: bool) -> str:
    parts: list[str] = []
    for token in tokens:
        if not isinstance(token, dict):
            continue
        if bool(token.get("is_final")) is not final:
            continue
        if token.get("translation_status") == "translation":
            continue
        text = token.get("text")
        if not isinstance(text, str) or not text:
            continue
        if text.startswith("<") and text.endswith(">"):
            continue
        parts.append(text)
    return "".join(parts).strip()
