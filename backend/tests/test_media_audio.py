"""ffmpeg-backed media→audio extraction (``app.core.media_audio``).

Runs the REAL ffmpeg binary on tiny synthesized files: extraction is the load-
bearing step for every video import (Telegram, web, Mac), so a mocked-only
suite would miss argument/exit-code regressions. ffmpeg ships in the backend
Docker image and on dev machines (pydub already requires it).
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.core.media_audio import (
    MediaAudioExtractionError,
    extract_audio_to_flac,
    is_audio_media_requiring_normalization,
    is_video_media,
    media_requires_audio_extraction,
    probe_media_duration_seconds,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg binary not available"
)


def _make_test_video(path, *, with_audio: bool = True, seconds: float = 1.0) -> None:
    """Synthesize a tiny mp4 (320x240 test pattern, optional 440 Hz tone)."""
    command = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error"]
    command += ["-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate=10"]
    if with_audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac", "-shortest"]
    command += [str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)


@pytest.mark.asyncio
async def test_extracts_flac_from_real_mp4(tmp_path):
    source = tmp_path / "clip.mp4"
    _make_test_video(source)
    dest = tmp_path / "clip.stt.flac"

    await extract_audio_to_flac(source, dest)

    assert dest.exists() and dest.stat().st_size > 0
    header = dest.read_bytes()[:4]
    assert header == b"fLaC"
    duration = await probe_media_duration_seconds(dest)
    assert duration is not None and 0.5 <= duration <= 2.0
    # The source is untouched — callers own its lifecycle.
    assert source.exists()


@pytest.mark.asyncio
async def test_video_without_audio_stream_raises_no_audio_stream(tmp_path):
    source = tmp_path / "mute.mp4"
    _make_test_video(source, with_audio=False)
    dest = tmp_path / "mute.stt.flac"

    with pytest.raises(MediaAudioExtractionError) as exc_info:
        await extract_audio_to_flac(source, dest)

    assert exc_info.value.code == "no_audio_stream"
    assert not dest.exists()


@pytest.mark.asyncio
async def test_garbage_input_raises_extract_failed(tmp_path):
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"this is not a video at all")
    dest = tmp_path / "broken.stt.flac"

    with pytest.raises(MediaAudioExtractionError) as exc_info:
        await extract_audio_to_flac(source, dest)

    assert exc_info.value.code in {"audio_extract_failed", "no_audio_stream"}
    assert not dest.exists()


@pytest.mark.asyncio
async def test_probe_duration_of_real_video(tmp_path):
    source = tmp_path / "probe.mp4"
    _make_test_video(source, seconds=2.0)

    duration = await probe_media_duration_seconds(source)

    assert duration is not None and 1.5 <= duration <= 3.0


@pytest.mark.asyncio
async def test_probe_duration_returns_none_for_garbage(tmp_path):
    source = tmp_path / "garbage.bin"
    source.write_bytes(b"nope")

    assert await probe_media_duration_seconds(source) is None


def test_media_type_policy():
    # Video → extract, regardless of how it was detected.
    assert media_requires_audio_extraction("mp4", "video/mp4") is True
    assert media_requires_audio_extraction("mkv", None) is True
    assert media_requires_audio_extraction("avi", "video/x-msvideo") is True
    # Provider-ready audio → pass through.
    assert media_requires_audio_extraction("mp3", "audio/mpeg") is False
    assert media_requires_audio_extraction("m4a", "audio/mp4") is False
    assert media_requires_audio_extraction("flac", "audio/flac") is False
    # Audio containers providers reject → extract on the import path.
    assert media_requires_audio_extraction("ogg", "audio/ogg") is True
    assert media_requires_audio_extraction("wma", "audio/x-ms-wma") is True
    assert is_audio_media_requiring_normalization("amr", None) is True
    # webm is audio when the content type says so, video otherwise.
    assert is_video_media("webm", "audio/webm") is False
    assert is_video_media("webm", "video/webm") is True
    assert is_video_media("webm", None) is True
