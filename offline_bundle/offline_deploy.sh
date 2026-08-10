#!/usr/bin/env bash
set -euo pipefail

# One-click offline deployment script (run on target machine)
# Usage:
#   ./offline_deploy.sh

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

DOCKER_CMD=""
if command -v docker >/dev/null 2>&1; then
  DOCKER_CMD="docker"
elif command -v sudo >/dev/null 2>&1 && sudo -n docker version >/dev/null 2>&1; then
  DOCKER_CMD="sudo docker"
else
  echo "[ERROR] docker not found (or not usable). Please install Docker first."
  exit 1
fi

compose_cmd() {
  if $DOCKER_CMD compose version >/dev/null 2>&1; then
    $DOCKER_CMD compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    if [[ "$DOCKER_CMD" == "sudo docker" ]]; then
      sudo docker-compose "$@"
    else
      docker-compose "$@"
    fi
  else
    echo "[ERROR] docker compose/docker-compose not found."
    exit 1
  fi
}

mkdir -p service scripts runtime runtime/logs

# 清理超过 30 天的轮转日志，避免历史备份长期占用磁盘。
find runtime/logs scripts -type f -name '*.log.*' -mtime +30 -print -delete 2>/dev/null || true

if [[ -f runtime/config.ini.example && ! -f runtime/config.ini ]]; then
  cp runtime/config.ini.example runtime/config.ini
  echo "[INFO] Created runtime/config.ini from template. Edit it before running task scripts."
fi
[[ -f runtime/config.ini ]] || touch runtime/config.ini
[[ -f runtime/script_descriptions.json ]] || echo "{}" > runtime/script_descriptions.json

if [[ ! -e scripts/config.ini ]]; then
  ln -s ../runtime/config.ini scripts/config.ini
fi

if [[ ! -f service/web_service.py ]]; then
  echo "[ERROR] service/web_service.py not found. Please verify offline bundle is complete."
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "APP_IMAGE=testing-tool-web:latest" > .env
fi

if [[ "${USE_OFFLINE_IMAGE:-0}" == "1" ]]; then
  if [[ ! -f image.tar ]]; then
    echo "[ERROR] USE_OFFLINE_IMAGE=1 but image.tar is missing"
    exit 1
  fi
  echo "[1/4] Loading image from image.tar"
  $DOCKER_CMD load -i image.tar
  BUILD_ARGS=(--no-build)
else
  echo "[1/4] Building image from source"
  BUILD_ARGS=(--build)
fi

echo "[2/4] Starting service"
compose_cmd -f docker-compose.yml up -d "${BUILD_ARGS[@]}"

echo "[3/4] Service status"
compose_cmd -f docker-compose.yml ps

echo "[4/4] Done"
echo "Mode: mounted layout (service/scripts/runtime)"
echo "Open in browser: http://<target-ip>:5000"
