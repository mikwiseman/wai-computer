import re
from pathlib import Path

import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def test_caddy_access_logs_are_disabled():
    caddyfile = (BACKEND_ROOT / "Caddyfile").read_text()

    assert "log {" not in caddyfile


def test_docker_compose_disables_gunicorn_access_log():
    compose = (BACKEND_ROOT / "docker-compose.yml").read_text()

    assert "--access-logfile -" not in compose
    assert "--error-logfile -" in compose


def test_celery_worker_runs_voice_identification_in_isolated_single_task_worker():
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.yml").read_text())
    api_service = compose["services"]["api"]
    worker_service = compose["services"]["celery-worker"]

    assert api_service["environment"]["VOICE_IDENTIFICATION_ENABLED"] == "false"
    assert worker_service["environment"]["VOICE_IDENTIFICATION_ENABLED"] == "true"
    assert "speechbrain_cache:/root/.cache/speechbrain" not in api_service["volumes"]
    assert "speechbrain_cache:/root/.cache/speechbrain" in worker_service["volumes"]
    assert "speechbrain_cache" in compose["volumes"]
    assert "--concurrency=1" in worker_service["command"]
    assert worker_service["deploy"]["resources"]["limits"]["memory"] == "1536M"


def test_server_build_only_starts_defined_compose_services():
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.yml").read_text())
    script = (REPO_ROOT / "scripts/server-build.sh").read_text()
    match = re.search(r"docker_compose up -d --remove-orphans (?P<services>[^\n]+)", script)
    assert match is not None

    requested = match.group("services").split()
    missing = sorted(set(requested) - set(compose["services"]))
    assert missing == []
