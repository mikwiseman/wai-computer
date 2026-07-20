"""Protocol translation between the WaiComputer realtime wire and OpenAI.

Clients speak one wire protocol on the ``/api/transcription/stream`` proxy:

- upstream (client → proxy): binary PCM16 frames plus JSON control messages
  ``{"type": "Finalize"}``, ``{"type": "CloseStream"}``, ``{"type": "KeepAlive"}``
- downstream (proxy → client): Deepgram-shaped ``Results`` frames
  (``channel.alternatives[0].transcript``, ``is_final``, ``from_finalize``),
  ``Metadata`` frames, and ``Error`` frames.

This module owns the pure translation state for one OpenAI realtime
transcription connection: PCM accounting for commit legality, per-item delta
accumulation for live interim frames, find/replace hint application, and
finalization bookkeeping. The websocket pumping lives in the route; every
decision lives here so it is unit-testable without sockets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from app.core.openai_realtime import (
    OPENAI_REALTIME_COMMIT_EMPTY_CODE,
    OPENAI_REALTIME_MIN_COMMIT_MS,
    OPENAI_REALTIME_SAMPLE_RATE,
    map_openai_error_code,
)

_BYTES_PER_MS = OPENAI_REALTIME_SAMPLE_RATE * 2 / 1000.0

DELTA_EVENT = "conversation.item.input_audio_transcription.delta"
COMPLETED_EVENT = "conversation.item.input_audio_transcription.completed"

FINALIZE_MARKER_FRAME = {"type": "Metadata", "request_id": "proxy-empty-finalize"}


class FinalizeAction(Enum):
    """What the bridge should do for a client ``Finalize`` message."""

    COMMIT = "commit"
    MARK_ONLY = "mark_only"


def compile_replacements(
    replacements: list[tuple[str, str]],
) -> list[tuple[re.Pattern[str], str]]:
    """Compile find/replace hints into boundary-aware case-insensitive patterns."""
    compiled: list[tuple[re.Pattern[str], str]] = []
    for find, replace in replacements:
        find_clean = find.strip()
        replace_clean = replace.strip()
        if not find_clean or not replace_clean:
            continue
        pattern = re.compile(
            r"(?<!\w)" + re.escape(find_clean) + r"(?!\w)",
            re.IGNORECASE | re.UNICODE,
        )
        compiled.append((pattern, replace_clean))
    return compiled


@dataclass
class OpenAIRealtimeBridgeState:
    """Mutable translation state for one bridged connection."""

    replacements: list[tuple[re.Pattern[str], str]] = field(default_factory=list)

    appended_ms_since_commit: float = 0.0
    appended_ms_total: float = 0.0
    commits_pending: int = 0
    finalize_requested: bool = False
    close_requested: bool = False
    client_gone: bool = False

    _item_text: dict[str, str] = field(default_factory=dict)
    _item_start_ms: dict[str, float] = field(default_factory=dict)
    _last_final_end_ms: float = 0.0

    def note_audio(self, byte_count: int) -> None:
        ms = byte_count / _BYTES_PER_MS
        self.appended_ms_since_commit += ms
        self.appended_ms_total += ms

    def finalize_action(self) -> FinalizeAction:
        """Decide how to finalize: real commit, or synthetic marker.

        OpenAI rejects commits with under ~100 ms of buffered audio
        (``input_audio_buffer_commit_empty``); with nothing meaningful to
        flush, the client still needs its finalization marker.
        """
        self.finalize_requested = True
        if self.appended_ms_since_commit >= OPENAI_REALTIME_MIN_COMMIT_MS:
            self.note_commit_sent()
            return FinalizeAction.COMMIT
        return FinalizeAction.MARK_ONLY

    def close_flush_needs_commit(self) -> bool:
        """Whether CloseStream should flush a tail commit before draining."""
        self.close_requested = True
        if self.commits_pending > 0:
            return False
        if self.appended_ms_since_commit >= OPENAI_REALTIME_MIN_COMMIT_MS:
            self.note_commit_sent()
            return True
        return False

    def note_commit_sent(self) -> None:
        self.commits_pending += 1
        self.appended_ms_since_commit = 0.0

    @property
    def drained(self) -> bool:
        return self.commits_pending == 0

    # ------------------------------------------------------------------
    # Upstream event translation

    def handle_upstream_event(self, event: dict) -> list[dict]:
        """Translate one OpenAI server event into downstream frames."""
        event_type = event.get("type")
        if event_type == DELTA_EVENT:
            return self._handle_delta(event)
        if event_type == COMPLETED_EVENT:
            return self._handle_completed(event)
        if event_type == "error":
            return self._handle_error(event)
        return []

    def _handle_delta(self, event: dict) -> list[dict]:
        item_id = str(event.get("item_id") or "item")
        delta = event.get("delta")
        if not isinstance(delta, str) or not delta:
            return []
        if item_id not in self._item_text:
            self._item_text[item_id] = ""
            self._item_start_ms[item_id] = self._last_final_end_ms
        self._item_text[item_id] += delta
        text = self._apply_replacements(self._item_text[item_id].strip())
        if not text:
            return []
        start_ms = self._item_start_ms[item_id]
        duration_ms = max(0.0, self.appended_ms_total - start_ms)
        return [self._results_frame(text, start_ms, duration_ms, is_final=False)]

    def _handle_completed(self, event: dict) -> list[dict]:
        item_id = str(event.get("item_id") or "item")
        transcript = event.get("transcript")
        if self.commits_pending > 0:
            self.commits_pending -= 1
        raw_text = transcript if isinstance(transcript, str) else self._item_text.get(item_id, "")
        start_ms = self._item_start_ms.pop(item_id, self._last_final_end_ms)
        self._item_text.pop(item_id, None)
        duration_ms = max(0.0, self.appended_ms_total - start_ms)
        self._last_final_end_ms = start_ms + duration_ms
        text = self._apply_replacements(raw_text.strip())
        if not text:
            # An empty final still finalizes the turn: the client's close
            # drain waits for a finalization marker, not for text.
            if self.finalize_requested or self.close_requested:
                return [dict(FINALIZE_MARKER_FRAME)]
            return []
        return [
            self._results_frame(
                text,
                start_ms,
                duration_ms,
                is_final=True,
                from_finalize=self.finalize_requested or self.close_requested,
            )
        ]

    def _handle_error(self, event: dict) -> list[dict]:
        error = event.get("error")
        error = error if isinstance(error, dict) else {}
        code = error.get("code")
        if code == OPENAI_REALTIME_COMMIT_EMPTY_CODE:
            # The buffer had nothing meaningful to commit. Resolve the pending
            # commit; when the client is finalizing this is a successful empty
            # finalization, not a failure.
            if self.commits_pending > 0:
                self.commits_pending -= 1
            if self.finalize_requested or self.close_requested:
                return [dict(FINALIZE_MARKER_FRAME)]
            return []
        message = error.get("message")
        return [
            {
                "type": "Error",
                "err_code": map_openai_error_code(code if isinstance(code, str) else None),
                "message": message
                if isinstance(message, str) and message
                else "Live transcription provider reported an error.",
            }
        ]

    # ------------------------------------------------------------------

    def _apply_replacements(self, text: str) -> str:
        for pattern, replacement in self.replacements:
            text = pattern.sub(replacement, text)
        return text

    @staticmethod
    def _results_frame(
        text: str,
        start_ms: float,
        duration_ms: float,
        *,
        is_final: bool,
        from_finalize: bool = False,
    ) -> dict:
        return {
            "type": "Results",
            "is_final": is_final,
            "from_finalize": from_finalize,
            "speech_final": is_final,
            "start": round(start_ms / 1000.0, 3),
            "duration": round(duration_ms / 1000.0, 3),
            "channel": {
                "alternatives": [
                    {
                        "transcript": text,
                        "confidence": 1.0 if is_final else 0.0,
                        "words": [],
                    }
                ]
            },
        }
