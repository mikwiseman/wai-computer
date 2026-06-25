"""Tests for the realtime dictation evaluator helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate-realtime-dictation.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("evaluate_realtime_dictation", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_summarize_reports_p95_and_error_runs() -> None:
    module = _load_module()
    rows = [
        {
            "mode": "prefetched",
            "provider": "deepgram",
            "model": "nova-3",
            "ok": True,
            "first_text_ms": 400,
            "final_ms": 1200,
            "connect_ms": 100,
            "mint_ms": 0,
            "wer": 0.01,
            "cer": 0.005,
        },
        {
            "mode": "prefetched",
            "provider": "deepgram",
            "model": "nova-3",
            "ok": False,
            "error": "provider closed",
        },
        {
            "mode": "prefetched",
            "provider": "deepgram",
            "model": "nova-3",
            "ok": True,
            "first_text_ms": 800,
            "final_ms": 1500,
            "connect_ms": 200,
            "mint_ms": 0,
            "wer": 0.02,
            "cer": 0.01,
        },
    ]

    summary = module.summarize(rows)

    assert summary == [
        {
            "mode": "prefetched",
            "provider": "deepgram",
            "model": "nova-3",
            "runs": 3,
            "ok_runs": 2,
            "error_runs": 1,
            "median_first_text_ms": 600,
            "p95_first_text_ms": 800,
            "median_final_ms": 1350,
            "p95_final_ms": 1500,
            "median_connect_ms": 150,
            "p95_connect_ms": 200,
            "median_mint_ms": 0,
            "p95_mint_ms": 0,
            "median_wer": 0.015,
            "p95_wer": 0.02,
            "median_cer": 0.0075,
            "p95_cer": 0.01,
        }
    ]


def test_gate_summary_fails_on_latency_or_error_regression() -> None:
    module = _load_module()
    summary = {
        "mode": "prefetched",
        "provider": "deepgram",
        "model": "nova-3",
        "runs": 20,
        "ok_runs": 19,
        "error_runs": 1,
        "p95_first_text_ms": 1_200,
        "p95_final_ms": 2_000,
        "p95_wer": 0.05,
        "p95_cer": 0.02,
    }

    failures = module.gate_summary(summary)

    assert failures == [
        "prefetched deepgram:nova-3 had 1 error runs",
        "prefetched deepgram:nova-3 p95_first_text_ms=1200ms > 1000ms",
    ]


def test_startup_buffered_chunk_count_matches_elapsed_connect_time() -> None:
    module = _load_module()

    assert module.startup_buffered_chunk_count(0, total_chunks=20) == 0
    assert module.startup_buffered_chunk_count(99, total_chunks=20) == 0
    assert module.startup_buffered_chunk_count(100, total_chunks=20) == 1
    assert module.startup_buffered_chunk_count(850, total_chunks=20) == 8
    assert module.startup_buffered_chunk_count(5_000, total_chunks=20) == 20
