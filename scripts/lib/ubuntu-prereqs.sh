#!/usr/bin/env bash
# Ubuntu Server host prerequisites: apt packages, Docker Engine, Compose v2.

require_root() {
  if [ "$(id -u)" -eq 0 ]; then
    return 0
  fi
  # ${SCRIPT_ARGS[*]} rather than $*: inside a function $* is the function's
  # own arguments, which are none, so the hint used to drop the flags the
  # operator had typed.
  die "This step needs root (apt / Docker). Re-run with: sudo $0 ${SCRIPT_ARGS[*]:-}"
}

require_ubuntu() {
  if [ ! -f /etc/os-release ]; then
    die "Cannot detect OS. This installer supports Ubuntu Server."
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  if [ "${ID:-}" != "ubuntu" ]; then
    die "Detected ${ID:-unknown}. This installer is for Ubuntu Server. Install Docker yourself, then use the source tree scripts."
  fi
  log "OS: Ubuntu ${VERSION_ID:-unknown} (${VERSION_CODENAME:-unknown})"
}

require_amd64() {
  local arch
  arch="$(uname -m)"
  case "$arch" in
    x86_64 | amd64)
      return 0
      ;;
  esac
  die "Architecture $arch is not supported for a new-server install (amd64 / x86_64 required)."
}

docker_stack_ready() {
  command -v docker >/dev/null 2>&1 \
    && docker info >/dev/null 2>&1 \
    && docker compose version >/dev/null 2>&1
}

install_ubuntu_base_packages() {
  export DEBIAN_FRONTEND=noninteractive
  log "Installing Ubuntu base packages (git, curl, ca-certificates, openssl)..."
  apt-get update -y
  apt-get install -y --no-install-recommends \
    apt-transport-https \
    ca-certificates \
    curl \
    git \
    gnupg \
    openssl \
    python3 \
    software-properties-common
}

install_docker_engine() {
  if docker_stack_ready; then
    log "Docker Engine and Compose v2 are already available."
    return 0
  fi

  require_root
  export DEBIAN_FRONTEND=noninteractive

  # shellcheck disable=SC1091
  . /etc/os-release
  local codename arch
  codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
  [ -n "$codename" ] || die "Cannot read Ubuntu codename from /etc/os-release."
  arch="$(dpkg --print-architecture)"

  log "Installing Docker Engine and Compose plugin from Docker's Ubuntu apt repo..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$arch" "$codename" >/etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y --no-install-recommends \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now docker
  fi

  docker_stack_ready || die "Docker installed but the daemon is not usable. Check: systemctl status docker"
  log "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo ok) and Compose are ready."
}

tune_host_for_redis() {
  if [ "$(id -u)" -ne 0 ]; then
    return 0
  fi
  if sysctl -w vm.overcommit_memory=1 >/dev/null 2>&1; then
    printf 'vm.overcommit_memory = 1\n' >/etc/sysctl.d/99-alpharouter-redis.conf
    log "Set vm.overcommit_memory=1 (Redis background save)."
  fi
}

add_sudo_user_to_docker_group() {
  local target="${SUDO_USER:-}"
  if [ -z "$target" ] || [ "$target" = "root" ]; then
    return 0
  fi
  if getent group docker >/dev/null 2>&1; then
    usermod -aG docker "$target" || true
    log "Added $target to the docker group (log out/in for a non-root docker CLI)."
  fi
}

install_ubuntu_prereqs() {
  require_ubuntu
  require_amd64
  if docker_stack_ready && command -v git >/dev/null 2>&1 && command -v curl >/dev/null 2>&1; then
    log "Host prerequisites are already present."
    tune_host_for_redis
    return 0
  fi
  require_root
  install_ubuntu_base_packages
  install_docker_engine
  tune_host_for_redis
  add_sudo_user_to_docker_group
}
