#!/usr/bin/env bash
# Xyberah one-command installer (Linux / macOS).
set -euo pipefail

echo ""
echo "=== Xyberah installer ==="

if ! docker version >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker and try again." >&2
  exit 1
fi

GENERATED=""
if [ ! -f .env ]; then
  cp .env.example .env
  PW="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
  # portable in-place edit
  sed "s|^XYBERAH_ADMIN_PASSWORD=.*|XYBERAH_ADMIN_PASSWORD=${PW}|" .env > .env.tmp && mv .env.tmp .env
  GENERATED="$PW"
  echo "Created .env with a generated admin password."
else
  echo ".env already exists; leaving it unchanged."
fi

echo ""
echo "Building and starting containers (first build downloads the scanners, ~15 min)..."
docker compose up -d --build

PORT="$(grep -E '^XYBERAH_HTTPS_PORT=' .env | cut -d= -f2)"; PORT="${PORT:-8443}"
USER_NAME="$(grep -E '^XYBERAH_ADMIN_USERNAME=' .env | cut -d= -f2)"

echo ""
echo "=== Xyberah is starting ==="
echo "URL:      https://localhost:${PORT}"
echo "Username: ${USER_NAME}"
if [ -n "$GENERATED" ]; then
  echo "Password: ${GENERATED}   (also in .env — change it after first login)"
else
  echo "Password: (see XYBERAH_ADMIN_PASSWORD in .env)"
fi
echo ""
echo "The certificate is self-signed, so your browser warns once. Continue past it,"
echo "or upload your own under Settings -> TLS certificate."
echo ""
echo "Logs:  docker compose logs -f backend"
