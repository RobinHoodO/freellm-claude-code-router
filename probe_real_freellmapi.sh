#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

FREE_LLM_API_BASE="${FREE_LLM_API_BASE:-http://127.0.0.1:3004/v1}"
FREE_LLM_API_TOKEN="${FREE_LLM_API_TOKEN:-$(ssh -o ClearAllForwardings=yes freellmapi-tunnel "sqlite3 /opt/freellmapi/data/freeapi.db \"select value from settings where key='unified_api_key';\"")}"
if [[ -x /usr/bin/python3 ]]; then
  PYTHON_BIN="${CLAUDE_ROUTER_PYTHON:-/usr/bin/python3}"
else
  PYTHON_BIN="${CLAUDE_ROUTER_PYTHON:-python3}"
fi

MODELS="${MODELS:-qwen/qwen3-coder:free,gemini-2.5-flash,z-ai/glm-4.5-air:free,codestral-latest,qwen/qwen3-next-80b-a3b-instruct:free,openai/gpt-oss-120b:free,openai/gpt-oss-20b:free,llama-3.3-70b-versatile}"

FREE_LLM_API_BASE="$FREE_LLM_API_BASE" \
env -u PYTHONHOME -u PYTHONPATH -u PYTHONEXECUTABLE "$PYTHON_BIN" freellm_router_mvp.py probe \
  --api-token "$FREE_LLM_API_TOKEN" \
  --output models.allowlist.real.json \
  --models "$MODELS"
