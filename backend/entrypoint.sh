#!/usr/bin/env bash
set -euo pipefail

# Seed tool venvs into the volume. Copies any tool missing from /opt/tools, so a
# new tool added to the image (e.g. modelaudit) appears in existing volumes too.
mkdir -p /opt/tools
for d in /opt/tools-seed/*/; do
  name=$(basename "$d")
  if [ ! -e "/opt/tools/$name" ]; then
    echo "[xyberah] seeding tool: $name"
    cp -a "$d" "/opt/tools/$name"
  fi
done
touch /opt/tools/.seeded

mkdir -p /data /config
# Default branding file so the login page is themed before any admin edits it
if [ ! -f /config/branding.yaml ]; then
  cp -n /opt/xyberah-app/engine/branding.default.yaml /config/branding.yaml 2>/dev/null || true
fi

exec "$@"
