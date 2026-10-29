#!/usr/bin/env bash
set -euo pipefail

# Seed the tools volume on first boot (keeps venvs at their original /opt/tools paths)
if [ ! -e /opt/tools/.seeded ]; then
  echo "[xyberah] seeding tool environments into /opt/tools ..."
  mkdir -p /opt/tools
  cp -a /opt/tools-seed/. /opt/tools/
  touch /opt/tools/.seeded
  echo "[xyberah] tools ready: garak, pyrit, inspect"
fi

mkdir -p /data /config
# Default branding file so the login page is themed before any admin edits it
if [ ! -f /config/branding.yaml ]; then
  cp -n /opt/xyberah-app/engine/branding.default.yaml /config/branding.yaml 2>/dev/null || true
fi

exec "$@"
