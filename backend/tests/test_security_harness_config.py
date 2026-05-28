from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_caddy_access_logs_are_disabled():
    caddyfile = (BACKEND_ROOT / "Caddyfile").read_text()

    assert "log {" not in caddyfile


def test_docker_compose_disables_gunicorn_access_log():
    compose = (BACKEND_ROOT / "docker-compose.yml").read_text()

    assert "--access-logfile -" not in compose
    assert "--error-logfile -" in compose


def test_celery_worker_runs_voice_identification_in_isolated_single_task_worker():
    compose = (BACKEND_ROOT / "docker-compose.yml").read_text()

    assert 'VOICE_IDENTIFICATION_ENABLED: "true"' in compose
    assert "speechbrain_cache:/root/.cache/speechbrain" in compose
    assert "speechbrain_cache:" in compose
    assert '"--concurrency=1"' in compose
    assert "memory: 1536M" in compose
