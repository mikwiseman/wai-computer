#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu VPS for self-hosted WaiComputer.
#
# This script installs host prerequisites, configures the basic firewall, clones
# WaiComputer, and then hands off to scripts/self-host-setup.sh. Provider API
# keys are prompted by self-host-setup.sh on this server; they are not passed in
# the browser command.
set -euo pipefail

ASSUME_YES=0
SETUP_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --yes|-y)
      ASSUME_YES=1
      SETUP_ARGS+=("$arg")
      ;;
    *)
      SETUP_ARGS+=("$arg")
      ;;
  esac
done

say()  { printf '\033[1;36m> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32mOK: %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

confirm() {
  local prompt="$1" answer
  if [[ "$ASSUME_YES" == 1 ]]; then
    return 0
  fi
  while true; do
    read -r -p "$prompt [Y/n]: " answer
    case "$answer" in
      ""|[Yy]|[Yy][Ee][Ss]) return 0 ;;
      [Nn]|[Nn][Oo]) return 1 ;;
      *) echo "Please answer yes or no." ;;
    esac
  done
}

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    fail "Run this as root on the VPS, or download it and run: sudo bash /tmp/waicomputer-self-host-bootstrap.sh"
  fi
}

require_ubuntu() {
  [[ -r /etc/os-release ]] || fail "/etc/os-release is missing; this bootstrap supports Ubuntu VPS images."
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || fail "This bootstrap supports Ubuntu only. Detected: ${PRETTY_NAME:-unknown}."
  [[ -n "${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}" ]] || fail "Ubuntu codename is missing from /etc/os-release."
}

apt_install_base_packages() {
  say "Installing base packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg git openssl ufw
}

remove_conflicting_docker_packages() {
  local package packages=()
  for package in docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc; do
    if dpkg -s "$package" >/dev/null 2>&1; then
      packages+=("$package")
    fi
  done
  if ((${#packages[@]})); then
    say "Removing conflicting Docker packages: ${packages[*]}"
    apt-get remove -y "${packages[@]}"
  fi
}

docker_compose_ready() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

install_docker_engine() {
  if docker_compose_ready; then
    ok "Docker Engine and Compose plugin are already installed"
    return 0
  fi

  say "Installing Docker Engine from Docker's official apt repository"
  remove_conflicting_docker_packages

  install -m 0755 -d /etc/apt/keyrings
  local key_file sources_file ubuntu_codename architecture
  key_file="$(mktemp)"
  sources_file="$(mktemp)"
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "$key_file"
  install -m 0644 "$key_file" /etc/apt/keyrings/docker.asc
  rm -f "$key_file"

  # shellcheck disable=SC1091
  . /etc/os-release
  ubuntu_codename="${UBUNTU_CODENAME:-$VERSION_CODENAME}"
  architecture="$(dpkg --print-architecture)"
  cat > "$sources_file" <<SOURCES
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $ubuntu_codename
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
SOURCES
  install -m 0644 "$sources_file" /etc/apt/sources.list.d/docker.sources
  rm -f "$sources_file"

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now docker
  fi

  docker compose version >/dev/null 2>&1
  ok "Docker Engine and Compose plugin are ready"
}

configure_firewall() {
  if ! confirm "Configure UFW to allow OpenSSH, HTTP, and HTTPS, then enable it?"; then
    say "Firewall configuration skipped by request. Open SSH, 80/tcp, and 443/tcp before using a public domain."
    return 0
  fi

  say "Configuring UFW firewall"
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
  ok "Firewall allows SSH, HTTP, and HTTPS"
}

checkout_waicomputer() {
  local repo_url target_dir
  repo_url="${WAICOMPUTER_REPO_URL:-https://github.com/mikwiseman/wai-computer.git}"
  target_dir="${WAICOMPUTER_DIR:-$HOME/wai-computer}"

  if [[ -d "$target_dir/.git" ]]; then
    say "Updating existing WaiComputer checkout at $target_dir"
    git -C "$target_dir" pull --ff-only
  elif [[ -e "$target_dir" ]]; then
    fail "$target_dir already exists and is not a git checkout. Set WAICOMPUTER_DIR to another path or move it first."
  else
    say "Cloning WaiComputer into $target_dir"
    git clone "$repo_url" "$target_dir"
  fi

  cd "$target_dir"
  chmod +x ./scripts/self-host-setup.sh
  ok "WaiComputer checkout ready"
}

main() {
  require_root
  require_ubuntu
  apt_install_base_packages
  install_docker_engine
  configure_firewall
  checkout_waicomputer
  exec ./scripts/self-host-setup.sh "${SETUP_ARGS[@]}"
}

main "$@"
