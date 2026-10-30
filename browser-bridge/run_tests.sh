#!/usr/bin/env bash
# ===========================================================================
# run_tests.sh — one command: install deps, (optionally) start the app under
# test, run the Xyberah/Promptfoo evaluation through the headless browser
# bridge, and write results to JSON + HTML. No human clicks required.
#
#   ./run_tests.sh
#
# CI tip: set CHAT_URL (and auth via CHAT_STORAGE_STATE) as env/secrets.
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")"

RESULTS_DIR="${RESULTS_DIR:-./results}"
CONFIG="${CONFIG:-promptfooconfig.yaml}"
mkdir -p "$RESULTS_DIR"

# --- 1. dependencies (idempotent) ------------------------------------------
if [ ! -d node_modules/playwright ]; then
  echo "[run] installing node dependencies..."
  npm install --no-audit --no-fund
fi
# Download the Chromium browser binary (+ OS libs on Linux). Safe to re-run.
echo "[run] ensuring Chromium is installed..."
npx playwright install --with-deps chromium

# --- 2. (optional) start the app under test --------------------------------
# Uncomment to boot a local app before testing and stop it afterwards.
# echo "[run] starting app under test..."
# ( cd ../your-app && npm run start >/"$RESULTS_DIR"/app.log 2>&1 & echo $! > "$RESULTS_DIR/app.pid" )
# trap 'kill "$(cat "$RESULTS_DIR/app.pid")" 2>/dev/null || true' EXIT
# npx wait-on "${CHAT_URL:-http://localhost:3000}" --timeout 60000

# --- 3. pick the engine: Xyberah's bundled promptfoo, else npx -------------
if command -v promptfoo >/dev/null 2>&1; then
  ENGINE="promptfoo"
elif command -v xyberah >/dev/null 2>&1; then
  ENGINE="xyberah"
else
  ENGINE="npx -y promptfoo@0.124.1"
fi
echo "[run] engine: $ENGINE"

# --- 4. run the evaluation (headless, non-interactive) ---------------------
# Multiple -o flags emit both JSON (machine) and HTML (human) in one run.
PROMPTFOO_DISABLE_TELEMETRY=1 CI=1 \
  $ENGINE eval \
    --config "$CONFIG" \
    --output "$RESULTS_DIR/results.json" \
    --output "$RESULTS_DIR/results.html" \
    --no-progress-bar

echo ""
echo "[run] done."
echo "[run]   JSON:  $RESULTS_DIR/results.json"
echo "[run]   HTML:  $RESULTS_DIR/results.html"

# --- 5. CI gate: exit non-zero if any test failed --------------------------
# Promptfoo already exits non-zero on failures; this makes the summary explicit.
node -e '
  const r = require("./'"$RESULTS_DIR"'/results.json");
  const s = (r.results && r.results.stats) || r.stats || {};
  const fail = s.failures ?? 0, pass = s.successes ?? 0;
  console.log(`[run] results: ${pass} passed, ${fail} failed`);
  process.exit(fail > 0 ? 1 : 0);
'
