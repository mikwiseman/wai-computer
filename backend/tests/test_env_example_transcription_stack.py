from pathlib import Path


def test_active_code_exposes_only_current_speech_to_text_stack():
    repo_root = Path(__file__).resolve().parents[2]
    search_roots = (
        "backend",
        "shared",
        "macos",
        "ios",
        "android",
        "web",
        "scripts",
        "docs",
        "README.md",
        ".git-hooks",
    )
    ignored_parts = {
        ".build",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".swiftpm",
        ".venv",
        ".venv-linux",
        "DerivedData",
        "__pycache__",
        "build",
        "node_modules",
        "coverage.xml",
        "dist",
    }
    ignored_names = {".env", ".env.local"}
    ignored_subpaths = {
        ("backend", "app", "db", "migrations", "versions"),
    }
    removed_stt_tokens = (
        "ELEVENLABS_" + "REALTIME_SPEECH_TO_TEXT_MODEL",
        "IN" + "WORLD_API_KEY",
        "DEEP" + "GRAM_API_KEY",
        "SON" + "IOX_API_KEY",
        "scribe_v2" + "_realtime",
        "realtime_" + "scribe",
        "gpt-realtime-" + "2",
        "deep" + "gram",
        "son" + "iox",
        "in" + "world",
        "whisper-" + "1",
        "gpt-4o-" + "transcribe",
    )

    matches: list[str] = []
    for root in search_roots:
        root_path = repo_root / root
        paths = [root_path] if root_path.is_file() else root_path.rglob("*")
        for path in paths:
            if not path.is_file():
                continue
            relative = path.relative_to(repo_root)
            if path.name in ignored_names:
                continue
            if any(
                part in ignored_parts or part.startswith(".venv")
                for part in relative.parts
            ):
                continue
            if any(relative.parts[: len(parts)] == parts for parts in ignored_subpaths):
                continue
            if path.suffix not in {
                "",
                ".env",
                ".example",
                ".kt",
                ".kts",
                ".md",
                ".py",
                ".sh",
                ".swift",
                ".ts",
                ".tsx",
                ".xml",
            }:
                continue
            content = path.read_text(errors="ignore")
            lowered = content.lower()
            for token in removed_stt_tokens:
                haystack = lowered if token.islower() else content
                if token in haystack:
                    matches.append(f"{relative}:{token}")

    assert matches == []


def test_env_example_exposes_only_current_stt_stack():
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    content = env_example.read_text()

    assert "OPENAI_API_KEY=" in content
    assert "ELEVENLABS_SPEECH_TO_TEXT_MODEL=scribe_v2" in content

    removed_stt_entries = (
        "ELEVENLABS_" + "REALTIME_SPEECH_TO_TEXT_MODEL",
        "IN" + "WORLD_API_KEY",
        "DEEP" + "GRAM_API_KEY",
        "SON" + "IOX_API_KEY",
        "scribe_v2" + "_realtime",
    )
    for entry in removed_stt_entries:
        assert entry not in content
