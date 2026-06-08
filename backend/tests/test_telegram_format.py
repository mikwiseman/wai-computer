"""Unit tests for the shared Telegram HTML converter (the **->&lt;b&gt; fix)."""

from app.core.telegram_format import telegram_html, telegram_inline


def test_markdown_bold_becomes_html_bold():
    # The core bug: '**1) Войско / обучение**' used to render literal asterisks.
    assert telegram_html("**1) Войско / обучение**") == "<b>1) Войско / обучение</b>"


def test_colon_header_fallback_still_bolds():
    assert telegram_html("2) Продажи и коммуникации:") == "<b>2) Продажи и коммуникации:</b>"


def test_bold_header_with_trailing_colon_is_not_double_wrapped():
    assert telegram_html("**Решения:**") == "<b>Решения:</b>"


def test_leading_bullets_are_preserved():
    # Image-1 style uses '- ' dashes; we preserve the author's marker, not force •.
    assert telegram_html("- пункт") == "- пункт"
    assert telegram_html("* пункт") == "* пункт"
    assert telegram_html("• пункт") == "• пункт"


def test_bullet_with_inline_bold():
    assert telegram_html("- **Дима** — созвон") == "- <b>Дима</b> — созвон"


def test_bulleted_line_ending_in_colon_is_not_bolded_as_header():
    # Bullets are items, not headers (matches the prior _telegram_summary_html intent).
    assert telegram_html("- срок:") == "- срок:"


def test_html_is_escaped():
    assert telegram_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_ampersand_inside_bold_is_escaped():
    assert telegram_html("**Quga & iCore**") == "<b>Quga &amp; iCore</b>"


def test_italic_underscore_and_star():
    assert telegram_html("_важно_") == "<i>важно</i>"
    assert telegram_html("это *важно* тут") == "это <i>важно</i> тут"


def test_snake_case_is_not_italicized():
    assert telegram_html("file_name_here стабилен") == "file_name_here стабилен"


def test_bare_asterisk_is_not_italicized():
    assert telegram_html("2 * 3 = 6") == "2 * 3 = 6"


def test_markdown_heading_becomes_bold():
    assert telegram_html("## План на 8 июня") == "<b>План на 8 июня</b>"


def test_blank_lines_preserved_between_blocks():
    assert telegram_html("**A**\n\n- x") == "<b>A</b>\n\n- x"


def test_full_plan_layout_matches_image_one_shape():
    src = (
        "**План на 8 июня 2020**\n"
        "\n"
        "**1) Войско / обучение**\n"
        "- Подготовить и провести лекцию\n"
        "\n"
        "2) Продажи и коммуникации:\n"
        "- Заняться продажами: Quga, iCore, ABD\n"
    )
    out = telegram_html(src)
    assert "<b>План на 8 июня 2020</b>" in out
    assert "<b>1) Войско / обучение</b>" in out
    assert "<b>2) Продажи и коммуникации:</b>" in out
    assert "- Подготовить и провести лекцию" in out
    assert "**" not in out  # no literal asterisks survive


def test_empty_string():
    assert telegram_html("") == ""
    assert telegram_html("   \n  ") == ""


def test_inline_converts_emphasis_but_not_colon_header():
    # A single value ending in ':' must NOT be bolded (it's a label/value, not a header).
    assert telegram_inline("срок:") == "срок:"
    assert telegram_inline("**Дима**") == "<b>Дима</b>"


def test_inline_escapes_html():
    assert telegram_inline("A & B <x>") == "A &amp; B &lt;x&gt;"


def test_inline_empty():
    assert telegram_inline("") == ""
