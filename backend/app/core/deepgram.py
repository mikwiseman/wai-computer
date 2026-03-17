"""Deepgram streaming transcription client."""

import json
import logging
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import websockets

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


@dataclass
class TranscriptResult:
    """Result from transcription."""

    text: str
    speaker: str | None
    is_final: bool
    start_ms: int
    end_ms: int
    confidence: float


class DeepgramStreamingClient:
    """Client for Deepgram real-time streaming transcription."""

    DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
    DEFAULT_MODEL = "nova-3"

    def __init__(
        self,
        on_transcript: Callable[[TranscriptResult], None] | None = None,
        language: str = "en",
        model: str = DEFAULT_MODEL,
    ):
        self.on_transcript = on_transcript
        self.language = language
        self.model = model
        self._ws: Any = None
        self._running = False

    def _build_url(self) -> str:
        """Build WebSocket URL with parameters."""
        params = [
            f"model={self.model}",
            f"language={self.language}",
            "punctuate=true",
            "diarize=true",
            "interim_results=true",
            "utterance_end_ms=1000",
            "vad_events=true",
            "encoding=linear16",
            "sample_rate=16000",
        ]
        if self.language == "multi":
            params.append("endpointing=100")
        return f"{self.DEEPGRAM_WS_URL}?{'&'.join(params)}"

    async def connect(self) -> bool:
        """Connect to Deepgram WebSocket."""
        if not settings.deepgram_api_key:
            raise ValueError("DEEPGRAM_API_KEY not configured")

        try:
            self._ws = await websockets.connect(
                self._build_url(),
                additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"},
            )
            self._running = True
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Deepgram: {e}") from e

    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio data to Deepgram."""
        if not self._ws or not self._running:
            raise RuntimeError("Deepgram connection is not active")

        await self._ws.send(audio_data)

    async def receive_transcripts(self) -> AsyncGenerator[TranscriptResult, None]:
        """Receive transcripts from Deepgram."""
        if not self._ws:
            logger.warning("receive_transcripts: no WebSocket connection")
            return

        msg_count = 0
        try:
            async for message in self._ws:
                if not self._running:
                    break

                msg_count += 1
                data = json.loads(message)
                msg_type = data.get("type", "unknown")

                if msg_count <= 5 or msg_count % 20 == 0:
                    logger.info(
                        f"Deepgram msg #{msg_count}: type={msg_type}, "
                        f"is_final={data.get('is_final', 'N/A')}"
                    )

                if msg_type == "Results":
                    channel = data.get("channel", {})
                    alternatives = channel.get("alternatives", [])
                    if alternatives:
                        alt = alternatives[0]
                        transcript = alt.get("transcript", "")
                        if transcript:
                            words = alt.get("words", [])
                            speaker = None
                            start_ms = 0
                            end_ms = 0

                            if words:
                                speaker = f"Speaker {words[0].get('speaker', 0)}"
                                start_ms = int(words[0].get("start", 0) * 1000)
                                end_ms = int(words[-1].get("end", 0) * 1000)

                            logger.info(
                                f"Deepgram transcript (final={data.get('is_final')}): "
                                f"{transcript[:80]}"
                            )
                            yield TranscriptResult(
                                text=transcript,
                                speaker=speaker,
                                is_final=data.get("is_final", False),
                                start_ms=start_ms,
                                end_ms=end_ms,
                                confidence=alt.get("confidence", 0.0),
                            )
        except Exception as e:
            logger.error(f"receive_transcripts error after {msg_count} msgs: {e}")
            self._running = False
            raise

    async def finish_stream(self) -> None:
        """Tell Deepgram we're done sending audio. It will send final results then close."""
        if self._ws and self._running:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                logger.info("Sent CloseStream to Deepgram")
            except Exception as e:
                logger.warning(f"Failed to send CloseStream: {e}")

    async def close(self) -> None:
        """Close the WebSocket connection."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None


def detect_wav_channels(audio_data: bytes) -> int:
    """Detect the number of channels from a WAV file header.

    Returns the channel count (1 for mono, 2 for stereo, etc.), or 1 if
    the data is not a valid WAV file.
    """
    if len(audio_data) < 44:
        return 1
    # Check RIFF/WAVE header
    if audio_data[:4] != b"RIFF" or audio_data[8:12] != b"WAVE":
        return 1
    # Channels are at bytes 22-23 (little-endian uint16)
    channels = int.from_bytes(audio_data[22:24], byteorder="little")
    return channels if channels > 0 else 1


async def transcribe_audio_file(
    audio_data: bytes,
    language: str = "en",
    model: str = DeepgramStreamingClient.DEFAULT_MODEL,
    content_type: str = "audio/wav",
    channels: int | None = None,
) -> list[TranscriptResult]:
    """Transcribe an audio file using Deepgram's REST API.

    When ``channels`` > 1, enables Deepgram's multichannel mode so that
    each audio channel is transcribed independently (e.g. mic on ch0,
    system audio on ch1).
    """
    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY not configured")

    # Auto-detect channels from WAV header when not specified
    if channels is None and content_type == "audio/wav":
        channels = detect_wav_channels(audio_data)
        if channels > 1:
            logger.info(f"Detected {channels}-channel WAV file, enabling multichannel")

    multichannel = channels is not None and channels > 1

    url = "https://api.deepgram.com/v1/listen"
    params: dict[str, str] = {
        "model": model,
        "language": language,
        "punctuate": "true",
        "diarize": "true",
        "utterances": "true",
    }
    if multichannel:
        params["multichannel"] = "true"
        params["channels"] = str(channels)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            params=params,
            headers={
                "Authorization": f"Token {settings.deepgram_api_key}",
                "Content-Type": content_type,
            },
            content=audio_data,
            timeout=300.0,
        )
        response.raise_for_status()
        data = response.json()

    results = []

    if multichannel:
        # Multichannel: Deepgram returns per-channel results
        channels_results = data.get("results", {}).get("channels", [])
        for ch_idx, channel_data in enumerate(channels_results):
            alternatives = channel_data.get("alternatives", [])
            if not alternatives:
                continue
            alt = alternatives[0]
            paragraphs = alt.get("paragraphs", {}).get("paragraphs", [])
            if paragraphs:
                # Use paragraphs for better sentence boundaries
                for para in paragraphs:
                    for sentence in para.get("sentences", []):
                        sentence_text = sentence.get("text", "").strip()
                        if not sentence_text:
                            continue
                        speaker = "You" if ch_idx == 0 else f"Speaker {ch_idx}"
                        results.append(
                            TranscriptResult(
                                text=sentence_text,
                                speaker=speaker,
                                is_final=True,
                                start_ms=int(sentence.get("start", 0) * 1000),
                                end_ms=int(sentence.get("end", 0) * 1000),
                                confidence=alt.get("confidence", 0.0),
                            )
                        )
            else:
                # Fallback: use the full transcript for this channel
                transcript = alt.get("transcript", "")
                if transcript:
                    words = alt.get("words", [])
                    start_ms = int(words[0].get("start", 0) * 1000) if words else 0
                    end_ms = int(words[-1].get("end", 0) * 1000) if words else 0
                    speaker = "You" if ch_idx == 0 else f"Speaker {ch_idx}"
                    results.append(
                        TranscriptResult(
                            text=transcript,
                            speaker=speaker,
                            is_final=True,
                            start_ms=start_ms,
                            end_ms=end_ms,
                            confidence=alt.get("confidence", 0.0),
                        )
                    )

        # Sort by start time for chronological order
        results.sort(key=lambda r: r.start_ms)
    else:
        # Single channel: use utterances as before
        utterances = data.get("results", {}).get("utterances", [])
        for utt in utterances:
            results.append(
                TranscriptResult(
                    text=utt.get("transcript", ""),
                    speaker=f"Speaker {utt.get('speaker', 0)}",
                    is_final=True,
                    start_ms=int(utt.get("start", 0) * 1000),
                    end_ms=int(utt.get("end", 0) * 1000),
                    confidence=utt.get("confidence", 0.0),
                )
            )

    return results
