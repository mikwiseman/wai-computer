"""Unit tests for the comparison-table engine (schema induction + extraction)."""

import pytest

from app.core.comparison import (
    ComparisonError,
    ComparisonItem,
    ComparisonResult,
    _Column,
    _ColumnSchema,
    _RowSchema,
    _RowValue,
    build_comparison,
    to_markdown,
)


def _items(n: int = 3) -> list[ComparisonItem]:
    return [
        ComparisonItem(item_id=f"id{i}", title=f"Video {i}", text=f"content about topic {i}")
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_build_comparison_requires_two_items() -> None:
    with pytest.raises(ComparisonError):
        await build_comparison(_items(1))


@pytest.mark.asyncio
async def test_build_comparison_induces_and_extracts() -> None:
    async def fake_inducer(items, intent):
        return _ColumnSchema(
            columns=[
                _Column(name="Thesis", type="text"),
                _Column(name="Length", type="number"),
            ],
            rationale="These differentiate the videos.",
        )

    async def fake_extractor(item, columns):
        # Item 1 omits Length -> null preserved.
        if item.item_id == "id1":
            return _RowSchema(values=[_RowValue(column="Thesis", value="solar wins")])
        return _RowSchema(
            values=[
                _RowValue(column="Thesis", value=f"thesis {item.item_id}"),
                _RowValue(column="Length", value="10"),
            ]
        )

    result = await build_comparison(
        _items(3), intent="by argument", inducer=fake_inducer, row_extractor=fake_extractor
    )
    assert [c["name"] for c in result.columns] == ["Thesis", "Length"]
    assert len(result.rows) == 3
    # Missing value is null, not fabricated.
    row1 = next(r for r in result.rows if r["item_id"] == "id1")
    assert row1["values"]["Length"] is None
    assert row1["values"]["Thesis"] == "solar wins"
    assert result.rationale.startswith("These differentiate")


@pytest.mark.asyncio
async def test_build_comparison_propagates_induction_failure() -> None:
    async def boom_inducer(items, intent):
        raise RuntimeError("model down")

    with pytest.raises(ComparisonError):
        await build_comparison(_items(2), inducer=boom_inducer)


def test_to_markdown_renders_table_with_nulls() -> None:
    result = ComparisonResult(
        columns=[{"name": "Thesis", "type": "text"}, {"name": "Length", "type": "number"}],
        rows=[
            {"item_id": "a", "title": "Vid A", "values": {"Thesis": "x", "Length": "10"}},
            {"item_id": "b", "title": "Vid B", "values": {"Thesis": "y", "Length": None}},
        ],
        rationale="r",
    )
    md = to_markdown(result)
    assert "| Item | Thesis | Length |" in md
    assert "| Vid A | x | 10 |" in md
    assert "| Vid B | y | — |" in md  # null rendered as em dash


def test_to_markdown_escapes_pipes() -> None:
    result = ComparisonResult(
        columns=[{"name": "Note", "type": "text"}],
        rows=[{"item_id": "a", "title": "A|B", "values": {"Note": "x|y"}}],
        rationale="r",
    )
    md = to_markdown(result)
    assert "A\\|B" in md
    assert "x\\|y" in md
