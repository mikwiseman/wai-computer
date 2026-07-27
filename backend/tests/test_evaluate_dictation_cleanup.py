"""Tests for the dictation cleanup evaluator's scoring helpers.

The evaluator is the only thing that can tell a legitimate cleanup edit from
meaning drift, so its scoring has to survive the edits cleanup is *supposed* to
make — dropped fillers, re-inflected Russian, reordered clauses — while still
catching lost facts.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate-dictation-cleanup.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("evaluate_dictation_cleanup", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_retention_ignores_fillers_and_function_words() -> None:
    module = _load_module()
    raw = "ну э-э-э короче нам надо запустить пилот в августе"
    cleaned = "Нам надо запустить пилот в августе."
    assert module.retention_score(raw, cleaned) == 1.0
    assert module.addition_score(raw, cleaned) == 0.0


def test_retention_tolerates_russian_reinflection() -> None:
    module = _load_module()
    raw = "созвон с командой роста во вторник"
    cleaned = "Созвон с командой роста во вторник."
    assert module.retention_score(raw, cleaned) == 1.0


def test_retention_catches_dropped_facts() -> None:
    module = _load_module()
    raw = "бюджет пятьдесят тысяч рублей, Аня готовит релизноуты, Сергей смотрит метрики"
    cleaned = "Аня готовит релизноуты."
    assert module.retention_score(raw, cleaned) < 0.5


def test_addition_flags_invented_content() -> None:
    module = _load_module()
    raw = "надо обновить документацию"
    cleaned = "Надо обновить документацию и провести ретроспективу с командой продаж."
    assert module.addition_score(raw, cleaned) > 0.4


def test_score_reports_contract_violations() -> None:
    module = _load_module()
    fixture = module.Fixture(
        id="demo",
        language="ru",
        levels=("medium",),
        raw="созвон во вторник, точнее в среду",
        must_keep=("среду",),
        must_drop=("вторник",),
        never=("четверг",),
        note="",
    )
    result = module.score(fixture, "medium", "Созвон во вторник или четверг.", 400)
    assert result.ok is False
    assert result.missing_keep == ["среду"]
    assert result.surviving_drop == ["вторник"]
    assert result.invented == ["четверг"]


def test_score_accepts_a_correct_cleanup() -> None:
    module = _load_module()
    fixture = module.Fixture(
        id="demo",
        language="ru",
        levels=("medium",),
        raw="созвон во вторник, точнее в среду",
        must_keep=("среду",),
        must_drop=("вторник",),
        never=(),
        note="",
        # Dropping the retracted value is the point of this fixture, so it
        # states how much of itself is legitimately deletable.
        min_retention=0.5,
    )
    result = module.score(fixture, "medium", "Созвон в среду.", 400)
    assert result.ok is True


def test_gate_failures_flag_slow_and_failing_levels() -> None:
    module = _load_module()
    summary = {
        "medium": {
            "fixtures": 4,
            "errors": 0,
            "assertion_pass_rate": 0.75,
            "min_retention": 0.5,
            "mean_retention": 0.8,
            "max_addition": 0.2,
            "mean_addition": 0.05,
            "p50_latency_ms": 900.0,
            "p95_latency_ms": 4_000.0,
            "max_latency_ms": 4_200.0,
        }
    }
    failures = module.gate_failures(summary)
    assert any("assertion pass rate" in failure for failure in failures)
    assert any("p95 latency" in failure for failure in failures)


def test_score_flags_over_deletion_and_over_addition_per_fixture() -> None:
    module = _load_module()
    strict = module.Fixture(
        id="strict",
        language="ru",
        levels=("medium",),
        raw="бюджет пятьдесят тысяч, Аня готовит релизноуты, Сергей смотрит метрики",
        must_keep=("Аня",),
        must_drop=(),
        never=(),
        note="",
    )
    lossy = module.score(strict, "medium", "Аня готовит релизноуты.", 400)
    assert lossy.over_deleted is True
    assert lossy.ok is False

    invented = module.score(
        strict,
        "medium",
        "Бюджет пятьдесят тысяч, Аня готовит релизноуты, Сергей смотрит метрики "
        "и проводит ретроспективу с отделом продаж.",
        400,
    )
    assert invented.over_added is True
    assert invented.ok is False


def test_score_flags_typographic_substitution() -> None:
    module = _load_module()
    fixture = module.Fixture(
        id="typography",
        language="ru",
        levels=("light",),
        raw="во-первых чиним экспорт",
        must_keep=("во-первых",),
        must_drop=(),
        never=(),
        note="",
    )
    # U+2011 non-breaking hyphen: invisible in review, breaks a code search.
    result = module.score(fixture, "light", "Во\u2011первых, чиним экспорт.", 400)
    assert result.smart_punctuation == ["\u2011"]
    assert result.ok is False


def test_gate_failures_pass_a_healthy_level() -> None:
    module = _load_module()
    summary = {
        "light": {
            "fixtures": 4,
            "errors": 0,
            "assertion_pass_rate": 1.0,
            "min_retention": 0.98,
            "mean_retention": 0.99,
            "max_addition": 0.0,
            "mean_addition": 0.0,
            "p50_latency_ms": 300.0,
            "p95_latency_ms": 500.0,
            "max_latency_ms": 520.0,
        }
    }
    assert module.gate_failures(summary) == []


def test_fixture_corpus_is_well_formed() -> None:
    module = _load_module()
    fixtures = module.load_fixtures()
    assert len(fixtures) >= 12
    seen: set[str] = set()
    for fixture in fixtures:
        assert fixture.id not in seen
        seen.add(fixture.id)
        assert fixture.levels
        assert fixture.raw.strip()
        # A fixture that asserts nothing cannot fail, so it cannot protect anything.
        assert fixture.must_keep or fixture.must_drop or fixture.never
        # keep/drop terms describe the dictation, so at least the as-spoken
        # alternative has to be in it — otherwise the assertion is a typo that
        # can never be satisfied. A dictionary entry is the exception: it is
        # expected to replace something the transcript got wrong.
        sources = fixture.raw.casefold() + " " + " ".join(fixture.vocabulary).casefold()
        for term in (*fixture.must_keep, *fixture.must_drop):
            assert module.term_present(term, sources), (fixture.id, term)


def test_term_present_accepts_any_alternative() -> None:
    module = _load_module()
    assert module.term_present("двести пятьдесят шесть|256", "сборка 256 готова")
    assert module.term_present("девять девяносто девять|9,99", "цена 9,99 в месяц")
    assert not module.term_present("двести пятьдесят шесть|256", "сборка 257 готова")
