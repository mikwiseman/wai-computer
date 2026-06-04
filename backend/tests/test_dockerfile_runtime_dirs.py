"""Regression tests for backend container runtime directories."""

from pathlib import Path


def test_dockerfile_precreates_summary_audio_volume_mount() -> None:
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    mkdir_line = next(
        line for line in text.splitlines() if line.startswith("RUN mkdir -p /var/lib/waicomputer/")
    )

    assert "/var/lib/waicomputer/uploads" in mkdir_line
    assert "/var/lib/waicomputer/summary-audio" in mkdir_line
