#!/usr/bin/env bash
# Xyberah CI quality gate. Creates a scan from a saved target, waits, and exits
# non-zero if the gate fails - so it can block a merge/deploy.
#
#   XYBERAH_URL=https://xyberah.example XYBERAH_TOKEN=xyb_... \
#   SAVED_TARGET_ID=3 MAX_RISK=40 MAX_CRITICAL=0 ./ci_scan.sh
set -euo pipefail
: "${XYBERAH_URL:?set XYBERAH_URL}"; : "${XYBERAH_TOKEN:?set XYBERAH_TOKEN}"
CURL=(curl -sk -H "Authorization: Bearer ${XYBERAH_TOKEN}" -H "Content-Type: application/json")

gate=$(python3 - <<PY
import json,os
g={}
if os.getenv("MAX_RISK"): g["max_risk_score"]=int(os.environ["MAX_RISK"])
if os.getenv("MAX_FAILURES"): g["max_failures"]=int(os.environ["MAX_FAILURES"])
if os.getenv("MAX_CRITICAL"): g["max_critical"]=int(os.environ["MAX_CRITICAL"])
if os.getenv("MAX_HIGH"): g["max_high"]=int(os.environ["MAX_HIGH"])
print(json.dumps(g))
PY
)
body=$(python3 - <<PY
import json,os
b={"name":os.getenv("SCAN_NAME","CI scan"),"gate":json.loads('${gate}')}
if os.getenv("SAVED_TARGET_ID"): b["saved_target_id"]=int(os.environ["SAVED_TARGET_ID"])
if os.getenv("TOOLS_JSON"): b["tools"]=json.loads(os.environ["TOOLS_JSON"])
print(json.dumps(b))
PY
)
echo "[ci] starting scan..."
resp=$("${CURL[@]}" -X POST "${XYBERAH_URL}/api/ci/scan" -d "${body}")
cid=$(echo "$resp" | python3 -c "import sys,json;print(json.load(sys.stdin)['campaign_id'])")
echo "[ci] campaign $cid running; polling..."
while true; do
  st=$("${CURL[@]}" "${XYBERAH_URL}/api/ci/scan/${cid}")
  done=$(echo "$st" | python3 -c "import sys,json;print(json.load(sys.stdin)['done'])")
  [ "$done" = "True" ] && break
  sleep 10
done
echo "$st" | python3 - <<PY
import sys,json
d=json.load(sys.stdin); s=d["summary"]; g=d["gate"]
print(f"[ci] risk={s['risk_score']} failed={s['failed']} critical={s['by_severity'].get('critical',0)} high={s['by_severity'].get('high',0)}")
if g["passed"]: print("[ci] GATE PASSED"); sys.exit(0)
print("[ci] GATE FAILED:", "; ".join(g["reasons"])); sys.exit(1)
PY
