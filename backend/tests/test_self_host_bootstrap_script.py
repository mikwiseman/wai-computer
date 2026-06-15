from pathlib import Path
import subprocess


ROOT_DIR = Path(__file__).resolve().parents[2]
BOOTSTRAP_SCRIPT = ROOT_DIR / "scripts" / "self-host-bootstrap.sh"
SELF_HOST_DOCS = ROOT_DIR / "docs" / "self-hosting.md"


def _script_text() -> str:
    return BOOTSTRAP_SCRIPT.read_text()


def test_bootstrap_script_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(BOOTSTRAP_SCRIPT)], check=True)


def test_bootstrap_installs_docker_from_official_apt_repository() -> None:
    text = _script_text()

    assert "https://download.docker.com/linux/ubuntu" in text
    assert "/etc/apt/keyrings/docker.asc" in text
    assert "/etc/apt/sources.list.d/docker.sources" in text
    assert "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin" in text
    assert "https://get.docker.com" not in text


def test_bootstrap_enables_firewall_only_after_allowing_required_ports() -> None:
    text = _script_text()

    ssh_rule = text.index("ufw allow OpenSSH")
    http_rule = text.index("ufw allow 80/tcp")
    https_rule = text.index("ufw allow 443/tcp")
    enable_rule = text.index("ufw --force enable")

    assert ssh_rule < enable_rule
    assert http_rule < enable_rule
    assert https_rule < enable_rule


def test_bootstrap_keeps_provider_keys_on_the_server_setup_script() -> None:
    text = _script_text()

    assert "set -euo pipefail" in text
    assert "exec ./scripts/self-host-setup.sh" in text
    assert "DEEPGRAM_API_KEY" not in text
    assert "OPENAI_API_KEY" not in text
    assert "CEREBRAS_API_KEY" not in text
    assert "| bash" not in text


def test_self_hosting_docs_show_the_bootstrap_command_first() -> None:
    text = SELF_HOST_DOCS.read_text()

    assert "self-host-bootstrap.sh" in text
    assert text.index("self-host-bootstrap.sh") < text.index("./scripts/self-host-setup.sh")
