#!/usr/bin/env python3
"""Generate the WaiComputer synthetic dictation benchmark JSON.

This script creates short deterministic speech fixtures with macOS `say`, sends
them through the configured file transcription providers, computes WER/CER, and
writes the public benchmark artifact consumed by the web page.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.core.transcription import transcribe_audio_file  # noqa: E402
from app.core.transcription_options import TRANSCRIPTION_OPTIONS, provider_is_configured  # noqa: E402


@dataclass(frozen=True)
class Fixture:
    id: str
    language: str
    voice: str
    text: str


FIXTURES = (
    Fixture(
        id="ru-product-dictation",
        language="ru",
        voice="Milena",
        text=(
            "Сегодня мы проверяем диктовку WaiComputer. "
            "Встреча началась в десять тридцать, следующий шаг — отправить отчёт команде."
        ),
    ),
    Fixture(
        id="en-product-dictation",
        language="en",
        voice="Samantha",
        text=(
            "WaiComputer should capture the last phrase without cutting it off. "
            "Please create a follow up reminder for Friday morning."
        ),
    ),
)


def normalize_text(value: str) -> list[str]:
    keep = []
    for char in value.casefold():
        keep.append(char if char.isalnum() or char.isspace() else " ")
    return " ".join("".join(keep).split()).split()


def edit_distance(left: list[str] | str, right: list[str] | str) -> int:
    a = list(left)
    b = list(right)
    previous = list(range(len(b) + 1))
    for i, item_a in enumerate(a, start=1):
        current = [i]
        for j, item_b in enumerate(b, start=1):
            cost = 0 if item_a == item_b else 1
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref_words = normalize_text(reference)
    hyp_words = normalize_text(hypothesis)
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return edit_distance(ref_words, hyp_words) / len(ref_words)


def character_error_rate(reference: str, hypothesis: str) -> float:
    ref = "".join(normalize_text(reference))
    hyp = "".join(normalize_text(hypothesis))
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def require_command(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required command not found: {name}")
    return path


def synthesize_fixture(fixture: Fixture, fixtures_dir: Path) -> Path:
    require_command("say")
    require_command("afconvert")
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    aiff_path = fixtures_dir / f"{fixture.id}.aiff"
    wav_path = fixtures_dir / f"{fixture.id}.wav"
    if wav_path.exists():
        return wav_path

    subprocess.run(
        [
            "say",
            "-v",
            fixture.voice,
            "-o",
            str(aiff_path),
            fixture.text,
        ],
        check=True,
    )
    subprocess.run(
        [
            "afconvert",
            "-f",
            "WAVE",
            "-d",
            "LEI16@16000",
            str(aiff_path),
            str(wav_path),
        ],
        check=True,
    )
    aiff_path.unlink(missing_ok=True)
    return wav_path


def wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


async def run_provider_fixture(provider: str, model: str, fixture: Fixture, path: Path) -> dict[str, Any]:
    audio = path.read_bytes()
    started = time.perf_counter()
    segments = await transcribe_audio_file(
        audio,
        language=fixture.language,
        model=model,
        provider=provider,
        content_type="audio/wav",
        channels=1,
    )
    elapsed = time.perf_counter() - started
    transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
    duration = wav_duration_seconds(path)
    return {
        "fixture_id": fixture.id,
        "language": fixture.language,
        "duration_seconds": round(duration, 3),
        "transcript": transcript,
        "wer": round(word_error_rate(fixture.text, transcript), 4),
        "cer": round(character_error_rate(fixture.text, transcript), 4),
        "latency_ms": round(elapsed * 1000),
        "speed_factor": round(duration / elapsed, 2) if elapsed > 0 else None,
    }


def aggregate(scores: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "wer": round(sum(score["wer"] for score in scores) / len(scores), 4),
        "cer": round(sum(score["cer"] for score in scores) / len(scores), 4),
        "latency_ms": round(sum(score["latency_ms"] for score in scores) / len(scores)),
        "speed_factor": round(sum(score["speed_factor"] or 0 for score in scores) / len(scores), 2),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(ROOT / "web/public/benchmarks/dictation/latest.json"),
        help="Benchmark JSON output path.",
    )
    parser.add_argument(
        "--fixtures-dir",
        default=str(ROOT / ".tmp/dictation-benchmark-fixtures"),
        help="Where generated WAV fixtures are cached.",
    )
    args = parser.parse_args()

    settings = get_settings()
    providers = [
        option
        for option in TRANSCRIPTION_OPTIONS["file_stt"]
        if provider_is_configured(option.provider, settings)
    ]
    if not providers:
        raise RuntimeError("No configured file transcription providers found.")

    fixtures_dir = Path(args.fixtures_dir)
    fixture_paths = {
        fixture.id: synthesize_fixture(fixture, fixtures_dir)
        for fixture in FIXTURES
    }

    model_results = []
    for option in providers:
        fixture_scores = []
        for fixture in FIXTURES:
            fixture_scores.append(
                await run_provider_fixture(option.provider, option.model, fixture, fixture_paths[fixture.id])
            )
        model_results.append(
            {
                "provider": option.provider,
                "model": option.model,
                "label": option.label,
                "description": option.description,
                "task": "file",
                "aggregate": aggregate(fixture_scores),
                "fixtures": fixture_scores,
            }
        )

    model_results.sort(key=lambda item: (item["aggregate"]["wer"], item["aggregate"]["latency_ms"]))
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "suite": "WaiComputer Synthetic Dictation v1",
        "source": "macOS say synthetic fixtures + real provider file transcription APIs",
        "fixtures": [
            {
                "id": fixture.id,
                "language": fixture.language,
                "voice": fixture.voice,
                "text": fixture.text,
                "duration_seconds": round(wav_duration_seconds(fixture_paths[fixture.id]), 3),
            }
            for fixture in FIXTURES
        ],
        "results": model_results,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    asyncio.run(main())
