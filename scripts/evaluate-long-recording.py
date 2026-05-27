#!/usr/bin/env python3
"""Evaluate production long-recording transcription end to end.

The script registers an isolated temporary account, pins the active file STT
model, uploads the same synthetic multi-speaker recording through the real
production API, then checks transcript quality, diarization, generated title,
summary, and exports.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
SILENCE_MS = 450


@dataclass(frozen=True)
class ModelCandidate:
    provider: str
    model: str
    label: str

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class Utterance:
    speaker: str
    voice: str
    text: str


@dataclass(frozen=True)
class Scenario:
    id: str
    language: str
    summary_language: str
    utterances: tuple[Utterance, ...]
    expected_tail: str

    @property
    def reference_text(self) -> str:
        return " ".join(utterance.text for utterance in self.utterances)

    @property
    def expected_speakers(self) -> int:
        return len({utterance.speaker for utterance in self.utterances})


DEFAULT_CANDIDATES = (
    ModelCandidate("elevenlabs", "scribe_v2", "ElevenLabs Scribe v2"),
)


SCENARIOS: dict[str, Scenario] = {
    "english_meeting": Scenario(
        id="english_meeting",
        language="en",
        summary_language="en",
        utterances=(
            Utterance(
                "Avery",
                "Samantha",
                "Good morning. Today we are testing WaiComputer long recording transcription.",
            ),
            Utterance(
                "Blake",
                "Daniel",
                "The first requirement is accurate speaker separation across a real meeting flow.",
            ),
            Utterance(
                "Avery",
                "Samantha",
                "The second requirement is a useful title and a concise summary after upload.",
            ),
            Utterance(
                "Blake",
                "Daniel",
                "Please capture action items, product decisions, and any important follow up.",
            ),
            Utterance(
                "Avery",
                "Samantha",
                "The benchmark should measure latency, speed factor, "
                "word error rate, and character error rate.",
            ),
            Utterance(
                "Blake",
                "Daniel",
                "The final sentence is important because lost tails are "
                "unacceptable in production.",
            ),
        ),
        expected_tail="lost tails are unacceptable in production",
    ),
    "mixed_ru_en": Scenario(
        id="mixed_ru_en",
        language="multi",
        summary_language="auto",
        utterances=(
            Utterance(
                "Mik",
                "Milena",
                "Привет. Мы проверяем длинную запись с русской речью и английскими терминами.",
            ),
            Utterance(
                "Alex",
                "Daniel",
                "The product requirement is fast transcription with clear speaker labels.",
            ),
            Utterance(
                "Mik",
                "Milena",
                "Нужно сохранить последнюю фразу и не потерять важное решение.",
            ),
            Utterance(
                "Alex",
                "Daniel",
                "The summary should mention action items, owners, and the final decision.",
            ),
            Utterance(
                "Mik",
                "Milena",
                "Последняя фраза нужна для проверки хвоста транскрипта.",
            ),
        ),
        expected_tail="проверки хвоста транскрипта",
    ),
}


def require_command(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"Required command not found: {name}")
    return path


def elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def normalize(text: str) -> str:
    chars = [char.casefold() if char.isalnum() or char.isspace() else " " for char in text]
    return " ".join("".join(chars).split())


def normalized_words(text: str) -> list[str]:
    normalized = normalize(text)
    return normalized.split() if normalized else []


def normalized_chars(text: str) -> list[str]:
    return list(normalize(text).replace(" ", ""))


def edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_value in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_value in enumerate(right, start=1):
            substitution = previous[right_index - 1] + (0 if left_value == right_value else 1)
            insertion = current[right_index - 1] + 1
            deletion = previous[right_index] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def error_rate(reference: list[str], hypothesis: list[str]) -> float | None:
    if not reference:
        return None
    return round(edit_distance(reference, hypothesis) / len(reference), 4)


def text_metrics(reference: str, hypothesis: str) -> dict[str, float | None]:
    return {
        "wer": error_rate(normalized_words(reference), normalized_words(hypothesis)),
        "cer": error_rate(normalized_chars(reference), normalized_chars(hypothesis)),
    }


def token_recall(reference: str, hypothesis: str) -> float | None:
    reference_tokens = normalized_words(reference)
    if not reference_tokens:
        return None
    hypothesis_tokens = set(normalized_words(hypothesis))
    matched = sum(1 for token in reference_tokens if token in hypothesis_tokens)
    return round(matched / len(reference_tokens), 4)


def read_wav_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != SAMPLE_RATE or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise RuntimeError(f"Fixture must be 16 kHz mono int16 WAV: {path}")
        return wav.readframes(wav.getnframes()), wav.getnframes()


def duration_seconds(path: Path) -> float:
    _, frames = read_wav_pcm(path)
    return frames / SAMPLE_RATE


def synthesize_utterance(path: Path, utterance: Utterance) -> None:
    require_command("say")
    require_command("afconvert")
    aiff_path = path.with_suffix(".aiff")
    subprocess.run(
        ["say", "-v", utterance.voice, "-o", str(aiff_path), utterance.text],
        check=True,
    )
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", str(aiff_path), str(path)],
        check=True,
    )
    aiff_path.unlink(missing_ok=True)


def ensure_fixture(scenario: Scenario) -> Path:
    fixture_dir = ROOT / "artifacts" / "benchmarks" / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixture_dir / f"{scenario.id}.wav"
    if fixture_path.exists():
        return fixture_path

    part_paths: list[Path] = []
    for index, utterance in enumerate(scenario.utterances, start=1):
        part_path = fixture_dir / f"{scenario.id}-{index:02d}.wav"
        synthesize_utterance(part_path, utterance)
        part_paths.append(part_path)

    silence = b"\x00" * (SAMPLE_RATE * BYTES_PER_SAMPLE * SILENCE_MS // 1000)
    with wave.open(str(fixture_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(BYTES_PER_SAMPLE)
        output.setframerate(SAMPLE_RATE)
        for index, part_path in enumerate(part_paths):
            pcm, _ = read_wav_pcm(part_path)
            if index:
                output.writeframes(silence)
            output.writeframes(pcm)

    for part_path in part_paths:
        part_path.unlink(missing_ok=True)
    return fixture_path


async def register_user(client: httpx.AsyncClient) -> dict[str, str]:
    email = f"long-recording-eval-{uuid.uuid4().hex[:12]}@example.com"
    password = f"eval-{uuid.uuid4().hex}"
    response = await client.post("/api/auth/register", json={"email": email, "password": password})
    response.raise_for_status()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def patch_settings(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    candidate: ModelCandidate,
    scenario: Scenario,
) -> None:
    response = await client.patch(
        "/api/settings",
        headers=headers,
        json={
            "file_stt_provider": candidate.provider,
            "file_stt_model": candidate.model,
            "default_language": scenario.language,
            "summary_language": scenario.summary_language,
        },
    )
    response.raise_for_status()


async def create_recording(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scenario: Scenario,
    candidate: ModelCandidate,
) -> str:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={
            "title": None,
            "type": "meeting",
            "language": scenario.language,
        },
    )
    response.raise_for_status()
    recording_id = response.json()["id"]
    print(f"{candidate.id} recording={recording_id}", flush=True)
    return recording_id


async def upload_recording(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    recording_id: str,
    fixture_path: Path,
) -> tuple[dict[str, Any], int]:
    start = time.perf_counter()
    with fixture_path.open("rb") as audio_file:
        response = await client.post(
            f"/api/recordings/{recording_id}/upload",
            headers=headers,
            files={"file": (fixture_path.name, audio_file, "audio/wav")},
        )
    response.raise_for_status()
    return response.json(), elapsed_ms(start)


async def get_json(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    path: str,
) -> dict[str, Any]:
    response = await client.get(path, headers=headers)
    response.raise_for_status()
    return response.json()


async def post_json(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    path: str,
) -> tuple[dict[str, Any], int]:
    start = time.perf_counter()
    response = await client.post(path, headers=headers)
    response.raise_for_status()
    return response.json(), elapsed_ms(start)


async def export_lengths(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    recording_id: str,
) -> dict[str, int]:
    lengths: dict[str, int] = {}
    for fmt in ("markdown", "txt", "srt"):
        response = await client.get(
            f"/api/recordings/{recording_id}/export",
            headers=headers,
            params={"format": fmt},
        )
        response.raise_for_status()
        lengths[fmt] = len(response.content)
    return lengths


async def cleanup_recording(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    recording_id: str,
) -> None:
    response = await client.delete(
        f"/api/recordings/{recording_id}",
        headers=headers,
        params={"permanent": "true"},
    )
    response.raise_for_status()


def transcript_text(recording: dict[str, Any]) -> str:
    segments = recording.get("segments")
    if not isinstance(segments, list):
        return ""
    return " ".join(str(segment.get("content") or "").strip() for segment in segments).strip()


def segment_speakers(recording: dict[str, Any]) -> list[str]:
    speakers: list[str] = []
    segments = recording.get("segments")
    if not isinstance(segments, list):
        return speakers
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        speaker = segment.get("raw_label") or segment.get("speaker") or segment.get("display_name")
        if isinstance(speaker, str) and speaker and speaker not in speakers:
            speakers.append(speaker)
    return speakers


def summary_counts(recording: dict[str, Any], summary: dict[str, Any] | None) -> dict[str, Any]:
    active_summary = summary if summary is not None else recording.get("summary")
    highlights = (
        recording.get("highlights") if isinstance(recording.get("highlights"), list) else []
    )
    action_items = (
        recording.get("action_items") if isinstance(recording.get("action_items"), list) else []
    )
    if not isinstance(active_summary, dict):
        active_summary = {}
    return {
        "summary_present": bool(str(active_summary.get("summary") or "").strip()),
        "key_points_count": len(active_summary.get("key_points") or []),
        "topics_count": len(active_summary.get("topics") or []),
        "decisions_count": len(active_summary.get("decisions") or []),
        "highlights_count": len(highlights),
        "action_items_count": len(action_items),
    }


async def evaluate_candidate(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scenario: Scenario,
    candidate: ModelCandidate,
    fixture_path: Path,
    *,
    cleanup: bool,
) -> dict[str, Any]:
    await patch_settings(client, headers, candidate, scenario)
    recording_id = await create_recording(client, headers, scenario, candidate)
    audio_duration_seconds = duration_seconds(fixture_path)

    result: dict[str, Any] = {
        "scenario": scenario.id,
        "provider": candidate.provider,
        "model": candidate.model,
        "label": candidate.label,
        "recording_id": recording_id,
        "audio_duration_seconds": round(audio_duration_seconds, 3),
    }

    try:
        recording, upload_ms = await upload_recording(client, headers, recording_id, fixture_path)
        result["upload_ms"] = upload_ms
        result["speed_factor"] = round(audio_duration_seconds / (upload_ms / 1000), 2)
        result["status"] = recording.get("status")
        result["failure_code"] = recording.get("failure_code")
        result["failure_message"] = recording.get("failure_message")

        recording = await get_json(client, headers, f"/api/recordings/{recording_id}")
        text = transcript_text(recording)
        result["hypothesis_text"] = text
        result.update(text_metrics(scenario.reference_text, text))
        result["tail_token_recall"] = token_recall(scenario.expected_tail, text)
        result["tail_ok"] = (result["tail_token_recall"] or 0.0) >= 0.75
        result["title_present"] = bool(str(recording.get("title") or "").strip())
        result["segment_count"] = len(recording.get("segments") or [])
        result["speaker_labels"] = segment_speakers(recording)
        result["speaker_label_count"] = len(result["speaker_labels"])

        if recording.get("status") == "ready":
            transcript_stats = await get_json(
                client, headers, f"/api/recordings/{recording_id}/transcript-stats"
            )
            speaker_stats = await get_json(
                client, headers, f"/api/recordings/{recording_id}/speaker-stats"
            )
            result["transcript_stats"] = transcript_stats
            result["speaker_stats"] = {
                "total_speakers": speaker_stats.get("total_speakers"),
                "total_duration_ms": speaker_stats.get("total_duration_ms"),
                "timeline_count": len(speaker_stats.get("timeline") or []),
            }
            summary, summary_ms = await post_json(
                client, headers, f"/api/recordings/{recording_id}/generate-summary"
            )
            result["summary_ms"] = summary_ms
            refreshed = await get_json(client, headers, f"/api/recordings/{recording_id}")
            result.update(summary_counts(refreshed, summary))
            result["export_lengths"] = await export_lengths(client, headers, recording_id)
        else:
            result["error"] = "recording did not reach ready status"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if cleanup:
            try:
                await cleanup_recording(client, headers, recording_id)
                result["cleaned_up"] = True
            except Exception as exc:
                result["cleanup_error"] = f"{type(exc).__name__}: {exc}"

    print(
        json.dumps(
            {
                "candidate": candidate.id,
                "status": result.get("status"),
                "wer": result.get("wer"),
                "cer": result.get("cer"),
                "upload_ms": result.get("upload_ms"),
                "speed_factor": result.get("speed_factor"),
                "speaker_label_count": result.get("speaker_label_count"),
                "summary_present": result.get("summary_present"),
                "error": result.get("error"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return result


def candidate_filter(value: str) -> set[str]:
    return {part.strip().lower() for part in value.split(",") if part.strip()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate production long-recording transcription models."
    )
    parser.add_argument("--base-url", default="https://wai.computer")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default="english_meeting",
    )
    parser.add_argument(
        "--candidates",
        default="all",
        help="Comma-separated provider:model ids, provider names, or 'all'.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "benchmarks" / "long-recording-eval.json",
    )
    parser.add_argument("--cleanup-recordings", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def selected_candidates(value: str) -> list[ModelCandidate]:
    if value == "all":
        return list(DEFAULT_CANDIDATES)
    requested = candidate_filter(value)
    candidates = [
        candidate
        for candidate in DEFAULT_CANDIDATES
        if candidate.id in requested or candidate.provider in requested
    ]
    if not candidates:
        raise RuntimeError(f"No file STT candidates matched: {value}")
    return candidates


def result_is_ok(result: dict[str, Any], scenario: Scenario) -> bool:
    if result.get("status") != "ready" or result.get("error"):
        return False
    if not result.get("tail_ok") or not result.get("title_present"):
        return False
    if not result.get("summary_present"):
        return False
    if result.get("speaker_label_count", 0) < min(2, scenario.expected_speakers):
        return False
    export_lengths = result.get("export_lengths")
    if not isinstance(export_lengths, dict) or any(value <= 0 for value in export_lengths.values()):
        return False
    return True


async def main() -> int:
    args = parse_args()
    scenario = SCENARIOS[args.scenario]
    candidates = selected_candidates(args.candidates)
    fixture_path = ensure_fixture(scenario)

    async with httpx.AsyncClient(base_url=args.base_url, timeout=900.0) as client:
        headers = await register_user(client)
        results = [
            await evaluate_candidate(
                client,
                headers,
                scenario,
                candidate,
                fixture_path,
                cleanup=args.cleanup_recordings,
            )
            for candidate in candidates
        ]

    payload = {
        "base_url": args.base_url,
        "scenario": scenario.id,
        "fixture": str(fixture_path),
        "reference_text": scenario.reference_text,
        "results": results,
        "generated_at_unix": round(time.time()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {args.output}", flush=True)

    if args.strict and not all(result_is_ok(result, scenario) for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
