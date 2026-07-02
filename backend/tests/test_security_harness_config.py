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


def test_api_runtime_trusts_forwarded_headers_from_internal_proxy():
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.yml").read_text())
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text()
    command = compose["services"]["api"]["command"][-1]

    assert "--forwarded-allow-ips='*'" in command
    assert '"--forwarded-allow-ips", "*"' in dockerfile


def test_celery_worker_runs_voice_identification_in_isolated_single_task_worker():
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.yml").read_text())
    api_service = compose["services"]["api"]
    worker_service = compose["services"]["celery-worker"]
    recording_worker_service = compose["services"]["celery-recording-worker"]

    assert api_service["environment"]["VOICE_IDENTIFICATION_ENABLED"] == "false"
    assert worker_service["environment"]["VOICE_IDENTIFICATION_ENABLED"] == "false"
    assert recording_worker_service["environment"]["VOICE_IDENTIFICATION_ENABLED"] == "true"
    assert "speechbrain_cache:/root/.cache/speechbrain" not in api_service["volumes"]
    assert "speechbrain_cache:/root/.cache/speechbrain" not in worker_service["volumes"]
    assert "speechbrain_cache:/root/.cache/speechbrain" in recording_worker_service["volumes"]
    assert "speechbrain_cache" in compose["volumes"]
    assert "--concurrency=1" in worker_service["command"]
    assert "--queues=celery" in worker_service["command"]
    assert "-B" in worker_service["command"]
    assert "--concurrency=1" in recording_worker_service["command"]
    assert "--queues=recording" in recording_worker_service["command"]
    assert "-B" not in recording_worker_service["command"]
    assert worker_service["deploy"]["resources"]["limits"]["memory"] == "768M"
    # 1536M -> 1280M (2026-07-02): funds the db bump to 768M after postgres
    # crashed into recovery mode under host memory pressure; children recycle
    # at --max-memory-per-child=900M so the worker never nears this limit.
    assert recording_worker_service["deploy"]["resources"]["limits"]["memory"] == "1280M"


def test_summary_generation_runs_in_dedicated_non_voice_worker():
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.yml").read_text())
    worker_service = compose["services"]["celery-worker"]
    summary_worker_service = compose["services"]["celery-summary-worker"]

    assert summary_worker_service["image"] == worker_service["image"]
    assert summary_worker_service["container_name"] == "waicomputer-celery-summary-worker"
    assert summary_worker_service["environment"]["VOICE_IDENTIFICATION_ENABLED"] == "false"
    assert "--queues=summary" in summary_worker_service["command"]
    assert "--concurrency=1" in summary_worker_service["command"]
    assert "-B" not in summary_worker_service["command"]
    assert "speechbrain_cache:/root/.cache/speechbrain" not in summary_worker_service["volumes"]
    assert summary_worker_service["deploy"]["resources"]["limits"]["memory"] == "512M"


def test_production_telegram_media_uses_local_bot_api_service():
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.yml").read_text())
    api_service = compose["services"]["api"]
    telegram_service = compose["services"]["telegram-bot-api"]

    assert telegram_service["image"] == "aiogram/telegram-bot-api:latest"
    assert telegram_service["environment"]["TELEGRAM_LOCAL"] == "true"
    assert "tg_api_data:/var/lib/telegram-bot-api" in telegram_service["volumes"]
    assert api_service["environment"]["TELEGRAM_BOT_API_BASE_URL"] == (
        "http://telegram-bot-api:8081"
    )
    assert api_service["environment"]["TELEGRAM_FILE_BASE_URL"] == (
        "http://telegram-bot-api:8081/file"
    )
    assert api_service["environment"]["TELEGRAM_LOCAL_FILE_ROOT"] == "/var/lib/telegram-bot-api"
    assert "tg_api_data:/var/lib/telegram-bot-api:ro" in api_service["volumes"]
    assert api_service["group_add"] == ["101"]
    assert api_service["depends_on"]["telegram-bot-api"]["condition"] == "service_started"
    assert "tg_api_data" in compose["volumes"]


def test_server_build_only_starts_defined_compose_services():
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.yml").read_text())
    script = (REPO_ROOT / "scripts/server-build.sh").read_text()
    match = re.search(r"DEPLOY_SERVICES=\((?P<services>[^)]+)\)", script)
    assert match is not None

    requested = match.group("services").split()
    assert "telegram-bot-api" in requested
    assert "celery-recording-worker" in requested
    assert "celery-summary-worker" in requested
    missing = sorted(set(requested) - set(compose["services"]))
    assert missing == []


def test_server_build_manages_recording_worker_during_deploy():
    script = (REPO_ROOT / "scripts/server-build.sh").read_text()

    assert (
        "docker_compose up -d --no-build --pull never "
        "celery-worker celery-recording-worker celery-summary-worker"
        in script
    )
    assert (
        "docker_compose stop celery-worker celery-recording-worker celery-summary-worker"
        in script
    )
    assert "waicomputer-celery-recording-worker" in script
    assert "Celery recording worker health check" in script


def test_server_build_manages_summary_worker_during_deploy():
    script = (REPO_ROOT / "scripts/server-build.sh").read_text()

    assert (
        "docker_compose up -d --no-build --pull never "
        "celery-worker celery-recording-worker celery-summary-worker"
        in script
    )
    assert (
        "docker_compose stop celery-worker celery-recording-worker celery-summary-worker"
        in script
    )
    assert "waicomputer-celery-summary-worker" in script
    assert "Celery summary worker health check" in script


def test_server_build_restarts_celery_after_interrupted_service_swap_without_building():
    script = (REPO_ROOT / "scripts/server-build.sh").read_text()

    assert "RESTART_CELERY_ON_EXIT=false" in script
    assert (
        "docker_compose up -d --no-build --pull never "
        "celery-worker celery-recording-worker celery-summary-worker"
    ) in script
    swap_start = script.index(
        "RESTART_CELERY_ON_EXIT=true\n"
        "docker_compose up \\"
    )
    worker_ready = script.index('"Celery summary worker health check"')
    swap_done = script.index("RESTART_CELERY_ON_EXIT=false", swap_start)
    assert swap_start < worker_ready < swap_done


def test_server_build_aligns_telegram_webhook_after_public_health():
    script = (REPO_ROOT / "scripts/server-build.sh").read_text()

    assert "scripts/configure-telegram-webhook.py" in script
    assert "docker_compose exec -T api python - <" in script
    assert script.index("Caddy HTTP health check") < script.index(
        "scripts/configure-telegram-webhook.py"
    )


def test_server_build_refuses_to_restart_active_transcription_tasks():
    script = (REPO_ROOT / "scripts/server-build.sh").read_text()

    assert 'ALLOW_ACTIVE_TRANSCRIPTION_DEPLOY="${ALLOW_ACTIVE_TRANSCRIPTION_DEPLOY:-0}"' in script
    assert "waicomputer-celery-worker" in script
    assert "waicomputer-celery-recording-worker" in script
    assert "app.tasks.media_import.import_uploaded_media" in script
    assert "app.tasks.recording_audio_processing.process_staged_recording_upload" in script
    assert "refusing to deploy while Celery has active transcription work" in script
    guard_call = "require_disk_headroom\nassert_no_active_transcription_tasks"
    assert guard_call in script
    assert script.index(guard_call) < script.index(
        'if [[ "$ALLOW_SERVER_SIDE_BUILD" == "1" ]]'
    )


def test_server_build_prunes_stale_deploy_images_before_disk_check():
    script = (REPO_ROOT / "scripts/server-build.sh").read_text()

    assert "prune_stale_deploy_images" in script
    assert 'keep_images=("$WAICOMPUTER_BACKEND_IMAGE" "$WAICOMPUTER_WEB_IMAGE")' in script
    assert "docker ps -a --format '{{.Image}}'" in script
    assert "Removing stale WaiComputer deploy images" in script
    prune_call = (
        "docker_compose config >/dev/null\n"
        "prune_stale_deploy_images\n"
        "require_disk_headroom"
    )
    assert prune_call in script


def test_production_compose_uses_sha_tagged_deploy_images():
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.yml").read_text())

    assert compose["services"]["api"]["image"] == (
        "${WAICOMPUTER_BACKEND_IMAGE:-waicomputer-backend:local}"
    )
    assert compose["services"]["celery-worker"]["image"] == compose["services"]["api"]["image"]
    assert (
        compose["services"]["celery-recording-worker"]["image"]
        == compose["services"]["api"]["image"]
    )
    assert (
        compose["services"]["celery-summary-worker"]["image"]
        == compose["services"]["api"]["image"]
    )
    assert compose["services"]["web"]["image"] == (
        "${WAICOMPUTER_WEB_IMAGE:-waicomputer-web:local}"
    )


def test_deploy_builds_and_loads_images_before_remote_swap():
    script = (REPO_ROOT / "scripts/deploy-api.sh").read_text()

    assert 'DEPLOY_IMAGE_SOURCE="${DEPLOY_IMAGE_SOURCE:-local}"' in script
    assert 'DEPLOY_IMAGE_PLATFORM="${DEPLOY_IMAGE_PLATFORM:-linux/amd64}"' in script
    assert "docker buildx build" in script
    assert "docker save" in script
    assert "docker load" in script
    assert "ALLOW_SERVER_SIDE_BUILD='0'" in script


def test_deploy_forwards_active_transcription_override_to_remote_build():
    script = (REPO_ROOT / "scripts/deploy-api.sh").read_text()

    assert 'ALLOW_ACTIVE_TRANSCRIPTION_DEPLOY="${ALLOW_ACTIVE_TRANSCRIPTION_DEPLOY:-0}"' in script
    assert "ALLOW_ACTIVE_TRANSCRIPTION_DEPLOY='${ALLOW_ACTIVE_TRANSCRIPTION_DEPLOY}'" in script


def test_server_side_image_builds_require_explicit_opt_in():
    script = (REPO_ROOT / "scripts/server-build.sh").read_text()

    assert 'ALLOW_SERVER_SIDE_BUILD="${ALLOW_SERVER_SIDE_BUILD:-0}"' in script
    assert 'require_image "$WAICOMPUTER_BACKEND_IMAGE"' in script
    assert 'require_image "$WAICOMPUTER_WEB_IMAGE"' in script
    assert "Server-side image builds are disabled" in script
    server_build_pattern = (
        r'if \[\[ "\$ALLOW_SERVER_SIDE_BUILD" == "1" \]\]; then'
        r".*docker_compose_timeout build api.*fi"
    )
    assert re.search(
        server_build_pattern,
        script,
        re.DOTALL,
    )
