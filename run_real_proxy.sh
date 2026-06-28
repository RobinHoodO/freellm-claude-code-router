#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

FREE_LLM_API_BASE="${FREE_LLM_API_BASE:-http://127.0.0.1:3004/v1}"
FREE_LLM_API_TOKEN="${FREE_LLM_API_TOKEN:-$(ssh -o ClearAllForwardings=yes freellmapi-tunnel "sqlite3 /opt/freellmapi/data/freeapi.db \"select value from settings where key='unified_api_key';\"")}"
ALLOWLIST="${ALLOWLIST:-models.allowlist.real.json}"
PORT="${PORT:-8787}"
MODE="${CLAUDE_ROUTER_MODE:-v1}"
if [[ -x /usr/bin/python3 ]]; then
  PYTHON_BIN="${CLAUDE_ROUTER_PYTHON:-/usr/bin/python3}"
else
  PYTHON_BIN="${CLAUDE_ROUTER_PYTHON:-python3}"
fi

if [[ ! -f "$ALLOWLIST" ]]; then
  echo "Missing $ALLOWLIST. Run ./probe_real_freellmapi.sh first." >&2
  exit 1
fi

FREE_LLM_API_BASE="$FREE_LLM_API_BASE" \
env -u PYTHONHOME -u PYTHONPATH -u PYTHONEXECUTABLE "$PYTHON_BIN" freellm_router_mvp.py proxy \
  --api-token "$FREE_LLM_API_TOKEN" \
  --allowlist "$ALLOWLIST" \
  --port "$PORT" \
  --mode "$MODE"
