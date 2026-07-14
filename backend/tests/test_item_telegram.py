"""Unit tests for the Telegram item-reply formatter."""

from app.core.item_telegram import format_fetch_error_reply, format_item_reply
from app.models.item import Item, ItemSummary


def _item(title: str | None = "My Video") -> Item:
    return Item(
        user_id=None,
        source="telegram",
        kind="video",
        title=title,
        body="x",
        content_hash="h",
        state="raw",
    )


def test_format_reply_with_summary_and_moments() -> None:
    summary = ItemSummary(
        item_id=None,
        summary="A talk about solar economics.",
        key_moments=[
            {"timestamp": "00:30", "moment": "Thesis stated", "importance": "high"},
            {"timestamp": None, "moment": "Counterpoint raised", "importance": "medium"},
        ],
        action_items=[{"task": "Read the white paper", "priority": "high"}],
    )
    out = format_item_reply(_item(), summary)
    assert "<b>My Video</b>" in out
    assert "solar economics" in out
    assert "Ключевые моменты" in out
    assert "[00:30] Thesis stated" in out
    assert "• Counterpoint raised" in out  # no timestamp -> bullet
    assert "Задачи" in out
    assert "Read the white paper" in out


def test_format_reply_escapes_html() -> None:
    summary = ItemSummary(
        item_id=None, summary="a < b & c", key_moments=[], action_items=[]
    )
    out = format_item_reply(_item(title="A & B <x>"), summary)
    assert "&amp;" in out
    assert "&lt;" in out
    assert "<x>" not in out  # raw angle brackets escaped


def test_format_reply_without_summary() -> None:
    out = format_item_reply(_item(title=None), None)
    assert out == "Сохранил в память."


def test_format_reply_moments_capped() -> None:
    summary = ItemSummary(
        item_id=None,
        summary="s",
        key_moments=[
            {"timestamp": None, "moment": f"moment {i}", "importance": "low"}
            for i in range(20)
        ],
        action_items=[],
    )
    out = format_item_reply(_item(), summary)
    assert out.count("moment ") <= 8


def test_format_fetch_error_reply_escapes() -> None:
    out = format_fetch_error_reply("Instagram doesn't allow <apps> & bots")
    assert "&lt;apps&gt;" in out
    assert "&amp;" in out


def test_format_fetch_error_reply_localizes_twitter_code() -> None:
    # The English message stored for web is remapped to Russian for the bot.
    out = format_fetch_error_reply(
        "X (Twitter) doesn't allow apps to read posts. Paste the post text "
        "(or a screenshot) and I'll add it to your brain.",
        "twitter_share_required",
    )
    assert "X (Twitter) не даёт приложениям читать посты" in out
    assert "doesn't allow" not in out


def test_format_fetch_error_reply_unknown_code_passes_through() -> None:
    out = format_fetch_error_reply("Instagram doesn't allow <apps>", "mystery_code")
    # Unknown codes are not swallowed: the stored message renders (escaped).
    assert "Instagram" in out
    assert "&lt;apps&gt;" in out


def test_format_reply_youtube_moments_deep_link_into_video() -> None:
    item = _item()
    item.metadata_ = {"video_id": "dQw4w9WgXcQ", "transcript_source": "captions"}
    summary = ItemSummary(
        item_id=None,
        summary="s",
        key_moments=[
            {
                "timestamp": "01:10",
                "moment": "Big reveal",
                "importance": "high",
                "start_ms": 70_000,
            },
            # No start_ms -> plain [ts], never a broken link.
            {"timestamp": "02:00", "moment": "Wrap up", "importance": "low"},
        ],
        action_items=[],
    )
    out = format_item_reply(item, summary)
    assert '<a href="https://youtu.be/dQw4w9WgXcQ?t=70">[01:10]</a> Big reveal' in out
    assert "[02:00] Wrap up" in out


def test_format_reply_discloses_audio_stt_fallback() -> None:
    item = _item()
    item.metadata_ = {"video_id": "abc", "transcript_source": "audio_stt"}
    summary = ItemSummary(item_id=None, summary="s", key_moments=[], action_items=[])
    out = format_item_reply(item, summary)
    assert "расшифровал аудио" in out
