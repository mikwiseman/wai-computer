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
    assert "Key moments" in out
    assert "[00:30] Thesis stated" in out
    assert "• Counterpoint raised" in out  # no timestamp -> bullet
    assert "To do" in out
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
    assert out == "Saved to your brain."


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
