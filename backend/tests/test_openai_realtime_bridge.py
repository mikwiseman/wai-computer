"""Tests for the OpenAI ↔ WaiComputer wire-protocol translation state."""

from app.core.openai_realtime_bridge import (
    COMPLETED_EVENT,
    DELTA_EVENT,
    FINALIZE_MARKER_FRAME,
    FinalizeAction,
    OpenAIRealtimeBridgeState,
    compile_replacements,
)

# 24 kHz mono PCM16: 48 bytes per millisecond.
_BYTES_PER_MS = 48


def _state(replacements: list[tuple[str, str]] | None = None) -> OpenAIRealtimeBridgeState:
    return OpenAIRealtimeBridgeState(
        replacements=compile_replacements(replacements or []),
    )


def _delta(text: str, item_id: str = "item_1") -> dict:
    return {"type": DELTA_EVENT, "item_id": item_id, "delta": text}


def _completed(text: str | None, item_id: str = "item_1") -> dict:
    return {"type": COMPLETED_EVENT, "item_id": item_id, "transcript": text}


# ---------------------------------------------------------------------------
# Audio accounting + finalize decisions


def test_finalize_commits_with_enough_audio() -> None:
    state = _state()
    state.note_audio(200 * _BYTES_PER_MS)
    assert state.finalize_action() == FinalizeAction.COMMIT
    assert state.finalize_requested
    assert state.commits_pending == 1
    assert state.appended_ms_since_commit == 0.0


def test_finalize_marks_only_when_buffer_below_commit_floor() -> None:
    state = _state()
    state.note_audio(50 * _BYTES_PER_MS)
    assert state.finalize_action() == FinalizeAction.MARK_ONLY
    assert state.finalize_requested
    assert state.commits_pending == 0


def test_close_flush_commits_uncommitted_tail() -> None:
    state = _state()
    state.note_audio(500 * _BYTES_PER_MS)
    assert state.close_flush_needs_commit() is True
    assert state.close_requested
    assert state.commits_pending == 1


def test_close_flush_skips_commit_when_finalize_already_pending() -> None:
    state = _state()
    state.note_audio(500 * _BYTES_PER_MS)
    assert state.finalize_action() == FinalizeAction.COMMIT
    state.note_audio(500 * _BYTES_PER_MS)
    # A commit is already in flight: the drain wait covers the tail; a second
    # commit here would double-finalize.
    assert state.close_flush_needs_commit() is False
    assert state.commits_pending == 1


def test_drained_reflects_pending_commits() -> None:
    state = _state()
    assert state.drained
    state.note_audio(200 * _BYTES_PER_MS)
    state.finalize_action()
    assert not state.drained
    state.handle_upstream_event(_completed("done"))
    assert state.drained


# ---------------------------------------------------------------------------
# Delta / completed translation


def test_delta_accumulates_into_interim_results_frames() -> None:
    state = _state()
    state.note_audio(1_000 * _BYTES_PER_MS)
    first = state.handle_upstream_event(_delta(" Привет"))
    second = state.handle_upstream_event(_delta(", мир"))

    assert len(first) == 1 and len(second) == 1
    assert first[0]["type"] == "Results"
    assert first[0]["is_final"] is False
    assert first[0]["channel"]["alternatives"][0]["transcript"] == "Привет"
    assert second[0]["channel"]["alternatives"][0]["transcript"] == "Привет, мир"
    assert second[0]["channel"]["alternatives"][0]["confidence"] == 0.0


def test_completed_emits_final_frame_with_from_finalize() -> None:
    state = _state()
    state.note_audio(2_000 * _BYTES_PER_MS)
    state.handle_upstream_event(_delta("Привет, мир"))
    assert state.finalize_action() == FinalizeAction.COMMIT

    frames = state.handle_upstream_event(_completed("Привет, мир."))
    assert len(frames) == 1
    frame = frames[0]
    assert frame["is_final"] is True
    assert frame["from_finalize"] is True
    assert frame["channel"]["alternatives"][0]["transcript"] == "Привет, мир."
    assert frame["channel"]["alternatives"][0]["confidence"] == 1.0
    assert state.drained


def test_completed_without_finalize_is_plain_final() -> None:
    state = _state()
    state.note_audio(2_000 * _BYTES_PER_MS)
    frames = state.handle_upstream_event(_completed("Сегмент."))
    assert frames[0]["is_final"] is True
    assert frames[0]["from_finalize"] is False


def test_empty_completed_after_finalize_yields_marker_frame() -> None:
    state = _state()
    state.note_audio(2_000 * _BYTES_PER_MS)
    state.finalize_action()
    frames = state.handle_upstream_event(_completed("   "))
    assert frames == [FINALIZE_MARKER_FRAME]


def test_empty_completed_without_finalize_is_silent() -> None:
    state = _state()
    state.note_audio(2_000 * _BYTES_PER_MS)
    assert state.handle_upstream_event(_completed("")) == []


def test_second_item_interim_resets_after_completed() -> None:
    state = _state()
    state.note_audio(1_000 * _BYTES_PER_MS)
    state.handle_upstream_event(_delta("Первый", item_id="a"))
    state.handle_upstream_event(_completed("Первый.", item_id="a"))
    state.note_audio(1_000 * _BYTES_PER_MS)
    frames = state.handle_upstream_event(_delta("Второй", item_id="b"))
    assert frames[0]["channel"]["alternatives"][0]["transcript"] == "Второй"


def test_ignored_events_produce_no_frames() -> None:
    state = _state()
    for event_type in (
        "session.created",
        "session.updated",
        "input_audio_buffer.speech_started",
        "input_audio_buffer.speech_stopped",
        "input_audio_buffer.committed",
        "conversation.item.added",
        "conversation.item.done",
    ):
        assert state.handle_upstream_event({"type": event_type}) == []


# ---------------------------------------------------------------------------
# Errors


def test_commit_empty_error_after_finalize_is_benign_marker() -> None:
    state = _state()
    state.note_audio(200 * _BYTES_PER_MS)
    state.finalize_action()
    frames = state.handle_upstream_event(
        {
            "type": "error",
            "error": {
                "code": "input_audio_buffer_commit_empty",
                "message": "buffer too small",
            },
        }
    )
    assert frames == [FINALIZE_MARKER_FRAME]
    assert state.drained


def test_commit_empty_error_without_finalize_is_ignored() -> None:
    state = _state()
    frames = state.handle_upstream_event(
        {
            "type": "error",
            "error": {"code": "input_audio_buffer_commit_empty", "message": "nope"},
        }
    )
    assert frames == []


def test_other_errors_map_to_client_error_frames() -> None:
    state = _state()
    frames = state.handle_upstream_event(
        {
            "type": "error",
            "error": {"code": "insufficient_quota", "message": "Quota exceeded"},
        }
    )
    assert frames == [
        {
            "type": "Error",
            "err_code": "insufficient_quota",
            "message": "Quota exceeded",
        }
    ]


def test_error_without_message_uses_generic_text() -> None:
    state = _state()
    frames = state.handle_upstream_event({"type": "error", "error": {"code": "boom"}})
    assert frames[0]["err_code"] == "boom"
    assert "provider reported an error" in frames[0]["message"]


# ---------------------------------------------------------------------------
# Replacements


def test_replacements_apply_to_interims_and_finals_with_boundaries() -> None:
    state = _state([("вай компьютер", "WaiComputer"), ("ai", "AI")])
    state.note_audio(1_000 * _BYTES_PER_MS)
    interim = state.handle_upstream_event(_delta("запусти вай компьютер сейчас"))
    assert (
        interim[0]["channel"]["alternatives"][0]["transcript"]
        == "запусти WaiComputer сейчас"
    )
    # "ai" replaces only as a standalone word — "маintenance"-style substrings stay.
    state.finalize_action()
    final = state.handle_upstream_event(_completed("ai plays fair with maintain"))
    assert (
        final[0]["channel"]["alternatives"][0]["transcript"]
        == "AI plays fair with maintain"
    )


def test_compile_replacements_skips_blank_pairs() -> None:
    compiled = compile_replacements([("  ", "x"), ("find", "  "), ("a", "b")])
    assert len(compiled) == 1
