# FreeLLM Claude Router Handover

Last updated: 2026-06-28 (Updated at 11:45 AM)

---

## 🚀 Recent Resolution (June 28, 11:45 AM)

We recently resolved three critical issues that were causing the router to fail during testing:

### 1. Tool Bloat & Context Length Limit Exceeded
* **Issue**: Prompt + tools payload exceeded context length limits (estimating up to 178k input tokens).
* **Cause**: Claude Code injects rules and workspace skills under a `<system-reminder>` header in a `"role": "user"` block. The proxy's tool-pruner matched integration keywords within this block, attaching Cal, Stripe, Supabase, Apify, Beeper, Blotato, and Twenty MCP tools to every request.
* **Resolution**: Updated `freellm_router_mvp.py` to filter out `<system-reminder>` blocks before evaluating tools.
* **Result**: Tools payload shrank by **91.5%** (from 324k to 27k characters), fitting easily.

### 2. Stale SSH Tunnel (502 Bad Gateway)
* **Issue**: Requests timed out or returned HTTP 502.
* **Cause**: A stale background SSH tunnel process (from Wednesday) was holding local port `3004`, failing to forward traffic to remote port `3001` (FreeLLMAPI).
* **Resolution**: Terminated the stale SSH process. A healthy tunnel was automatically re-established.

### 3. Invalid API Key / 401 Unauthorized
* **Issue**: Upstream FreeLLMAPI returned `HTTP 401: Invalid API key`.
* **Cause**: The local proxy was not configured with the unified key and forwarded the client's `local-dev-token` to the remote server.
* **Resolution**: Retrieved the real unified API key from the remote SQLite database and updated the proxy request handler in `freellm_router_mvp.py` to extract bearer tokens safely. Restarted the local proxy with `--api-token` (read from `.env` — see `.env.example`).

---

## Project Location

Authoritative working folder:

```text
<repo-root>
```

Do not use the older Codex output copy under:

```text
<stale codex copy (deleted)>
```

That location is stale.

## User Goal

Build and test a local Claude Code routing gateway that lets Claude Code use the user's existing FreeLLMAPI service.

The user wanted multiple experimental versions:

```text
v1: one selected model
v2: task-aware single-model router
v3: multi-model ensemble router
v4: meta-router that chooses v1, v2, or v3
```

The commands should feel like the user's existing model launchers:

```bash
claude-routerv1
claude-routerv2
claude-routerv3
claude-routerv4
```

## Big Picture

Claude Code expects Anthropic-style endpoints:

```text
/v1/messages
/v1/messages/count_tokens
```

FreeLLMAPI exposes OpenAI-compatible endpoints:

```text
/v1/chat/completions
/v1/responses
/v1/embeddings
```

This project inserts a local adapter:

```text
Claude Code
  -> local Anthropic-compatible proxy
    -> FreeLLMAPI at http://127.0.0.1:3004/v1
      -> provider/model fallback inside FreeLLMAPI
```

## FreeLLMAPI

Live base URL:

```text
http://127.0.0.1:3004/v1
```

Dashboard:

```text
http://127.0.0.1:3004
```

iframe proxy:

```text
http://127.0.0.1:3014
```

The FreeLLMAPI key exists on the server. Do not hard-code it in docs or final messages. The launch scripts fetch it over SSH:

```bash
ssh -o ClearAllForwardings=yes freellmapi-tunnel \
  "sqlite3 /opt/freellmapi/data/freeapi.db \"select value from settings where key='unified_api_key';\""
```

The user has provided the key in chat before, but treat it as sensitive.

## Important Files

```text
freellm_router_mvp.py          main Python proxy, mock API, probe, smoke tests
README.md                     main overview
HANDOVER.md                   this handover document
VERSION-1.md                  v1 notes
VERSION-2.md                  v2 notes
VERSION-3.md                  v3 notes
VERSION-4.md                  v4 notes
start-here.html               clickable local map
models.allowlist.real.json    real tested allowlist
models.allowlist.example.json example allowlist
probe_real_freellmapi.sh      regenerate real allowlist
run_real_proxy.sh             manual proxy runner
```

Installed command wrappers:

```text
~/.local/bin/claude-router
~/.local/bin/claude-routerv1
~/.local/bin/claude-routerv2
~/.local/bin/claude-routerv3
~/.local/bin/claude-routerv4
```

The small version wrappers set `CLAUDE_ROUTER_MODE` and delegate to `~/.local/bin/claude-router`.

## Ports

Current intended local proxy ports:

```text
v1: http://127.0.0.1:8787
v2: http://127.0.0.1:8791
v3: http://127.0.0.1:8789
v4: http://127.0.0.1:8792
```

Notes:

```text
8788 was previously occupied by a local node process, so v2 moved to 8791.
8790 was previously occupied by a local node process, so v4 moved to 8792.
```

Logs and PID files:

```text
/tmp/claude-router-v1.log
/tmp/claude-router-v2.log
/tmp/claude-router-v3.log
/tmp/claude-router-v4.log

/tmp/claude-router-v1.pid
/tmp/claude-router-v2.pid
/tmp/claude-router-v3.pid
/tmp/claude-router-v4.pid
```

The launcher truncates the log on startup to avoid stale tracebacks being mistaken for current errors.

## Version Behavior

### v1

Command:

```bash
claude-routerv1
```

Behavior:

```text
One selected compatible model request.
FreeLLMAPI may still fallback internally to a provider/model that actually answers.
```

Default visible Claude model:

```text
qwen/qwen3-coder:free
```

### v2

Command:

```bash
claude-routerv2
```

Behavior:

```text
Classify request into a deterministic policy.
Choose one compatible model from that policy.
If the selected model fails/rate-limits, retry other compatible allowlisted models.
```

Policies currently include:

```text
long-context
coding
review
summarization
fast
```

The fallback implementation is in:

```text
ordered_fallback_models(...)
post_with_model_fallback(...)
```

### v3

Command:

```bash
claude-routerv3
```

Behavior:

```text
Text-only requests:
  ask multiple advisor models
  aggregate their answers into one final answer

Tool-bearing Claude Code requests:
  use safe v2 single-model path
```

If an advisor fails or rate-limits, v3 skips it. If all advisors fail, v3 falls back to one compatible single model.

Important function:

```text
run_v3_ensemble(...)
```

### v4

Command:

```bash
claude-routerv4
```

Behavior:

```text
Meta-router.
Chooses which router strategy to use: v1, v2, or v3.
```

Rules:

```text
tools present -> v2
very long context -> v2
coding/fixing/debugging/testing/review -> v2
compare/tradeoff/best approach/brainstorm/synthesize/strategy/architecture -> v3
short simple request -> v1
summary/overview -> v2
fallback -> v2
```

Important function:

```text
classify_v4_route(...)
```

Useful debug headers:

```text
x-router-mode
x-router-selected-version
x-router-selected-model
x-router-policy
x-router-route-reason
x-router-advisor-models
x-router-fallbacks
```

## Current Allowlisted Models

See:

```text
models.allowlist.real.json
```

Known candidates include:

```text
qwen/qwen3-coder:free
gemini-2.5-flash
z-ai/glm-4.5-air:free
openai/gpt-oss-120b:free
openai/gpt-oss-20b:free
llama-3.3-70b-versatile
```

Compatibility means:

```text
basic chat works
tool call shape works
context window is large enough for Claude Code startup/tool prompts
```

FreeLLMAPI can still route/fallback underneath, so the requested model and actual provider/model may differ.

## How To Test

First verify syntax:

```bash
cd <repo-root>
python3 -m py_compile freellm_router_mvp.py
bash -n ~/.local/bin/claude-router probe_real_freellmapi.sh run_real_proxy.sh
```

Check commands resolve:

```bash
for c in claude-routerv1 claude-routerv2 claude-routerv3 claude-routerv4; do
  command -v "$c"
done
```

Start/status each proxy:

```bash
claude-routerv1 --start-proxy && claude-routerv1 --status
claude-routerv2 --start-proxy && claude-routerv2 --status
claude-routerv3 --start-proxy && claude-routerv3 --status
claude-routerv4 --start-proxy && claude-routerv4 --status
```

Claude command marker tests:

```bash
claude-routerv1 -p 'Say ROUTER_V1_FULL_TEST_OK and nothing else.' --output-format text
claude-routerv2 -p 'Say ROUTER_V2_FULL_TEST_OK and nothing else.' --output-format text
claude-routerv3 -p 'Say ROUTER_V3_FULL_TEST_OK and nothing else.' --output-format text
claude-routerv4 -p 'Say ROUTER_V4_FULL_TEST_OK and nothing else.' --output-format text
```

Expected markers from the last full test pass:

```text
ROUTER_V1_FULL_TEST_OK
ROUTER_V2_FULL_TEST_OK
ROUTER_V3_FULL_TEST_OK
ROUTER_V4_FULL_TEST_OK
```

Direct v4 route proof:

```bash
curl -sS -D /tmp/routerv4-simple.headers http://127.0.0.1:8792/v1/messages \
  -H 'content-type: application/json' \
  -d '{"model":"qwen/qwen3-coder:free","max_tokens":30,"messages":[{"role":"user","content":"Say hello."}]}' \
  > /tmp/routerv4-simple.json
rg -i 'x-router' /tmp/routerv4-simple.headers
```

Expected:

```text
x-router-selected-version: v1
```

```bash
curl -sS -D /tmp/routerv4-compare.headers http://127.0.0.1:8792/v1/messages \
  -H 'content-type: application/json' \
  -d '{"model":"qwen/qwen3-coder:free","max_tokens":70,"messages":[{"role":"user","content":"Compare tradeoffs for router strategies."}]}' \
  > /tmp/routerv4-compare.json
rg -i 'x-router' /tmp/routerv4-compare.headers
```

Expected:

```text
x-router-selected-version: v3
```

```bash
curl -sS -D /tmp/routerv4-tools.headers http://127.0.0.1:8792/v1/messages \
  -H 'content-type: application/json' \
  -d '{"model":"qwen/qwen3-coder:free","max_tokens":60,"messages":[{"role":"user","content":"Call the ping tool with value ok."}],"tools":[{"name":"ping","description":"tool","input_schema":{"type":"object","properties":{"value":{"type":"string"}},"required":["value"]}}]}' \
  > /tmp/routerv4-tools.json
rg -i 'x-router' /tmp/routerv4-tools.headers
```

Expected:

```text
x-router-selected-version: v2
```

## Known Issues And Gotchas

### Python `encodings` Error

The user saw:

```text
Fatal Python error: Failed to import encodings module
ModuleNotFoundError: No module named 'encodings'
```

Cause:

```text
Broken PYTHONHOME, PYTHONPATH, or PYTHONEXECUTABLE leaking into router startup.
```

Fix already implemented:

```text
claude-router, probe_real_freellmapi.sh, and run_real_proxy.sh unset those variables before launching Python.
```

Override Python if needed:

```bash
CLAUDE_ROUTER_PYTHON=/path/to/python3 claude-routerv2
```

### Port Conflicts

The user previously hit:

```text
OSError: [Errno 48] Address already in use
```

Observed conflicts:

```text
8788: node process
8790: node process
```

Fix already implemented:

```text
v2 moved to 8791
v4 moved to 8792
```

Check listeners:

```bash
for p in 8787 8788 8789 8790 8791 8792; do
  echo "PORT $p"
  lsof -nP -iTCP:$p -sTCP:LISTEN || true
done
```

### FreeLLMAPI Rate Limits

The user saw 429-style failures:

```text
All models exhausted. Add more API keys or wait for rate limits to reset.
```

Fix already implemented:

```text
single-model routes now retry other compatible allowlisted models.
v3 skips failed advisors and can fall back to a single model.
```

### Claude Code Tool Requests

Claude Code often sends tool schemas even for simple `-p` prompts.

Implication:

```text
v3 may use v2 path for Claude Code tool-bearing requests.
v4 often chooses v2 for Claude Code requests because tools need one driver model.
```

This is intentional.

### Codex Tool Environment Reaping

When testing from inside this Codex environment, background proxies may sometimes disappear after a tool command exits. In the user's normal terminal, `claude-routervN --start-proxy` should persist normally.

If a proxy is not up, simply run:

```bash
claude-routervN --start-proxy
```

or run the command directly:

```bash
claude-routervN
```

## Design Notes

Router-R1 has not actually been integrated as the decision model yet.

Current routing is deterministic Python logic:

```text
choose_model(...)
classify_v2_policy(...)
classify_v4_route(...)
```

Safe future insertion point for Router-R1:

```text
request
  -> hard compatibility filter
    -> eligible models only
      -> Router-R1 chooses model or routing strategy
```

Do not let Router-R1 choose from the raw FreeLLMAPI model list. It should only see models that passed compatibility checks for the current request.

## Recommended Next Steps

1. Add automated integration test script that runs v1-v4 direct endpoint checks in one command.
2. Add better process management for start/stop/status, possibly a small Python supervisor instead of bash.
3. Add route logs in JSONL so the user can inspect which version/model was selected over time.
4. Add optional Router-R1 decision layer after the deterministic router is stable.
5. Add a browser UI page showing live status for v1-v4 ports and recent decisions.

## Last Known Good Verification

The last complete verification pass confirmed:

```text
v1 direct request works
v2 direct request works and falls back after selected model 429
v3 ensemble request works
v4 simple request -> v1
v4 comparison request -> v3
v4 tool request -> v2

claude-routerv1 -> ROUTER_V1_FULL_TEST_OK
claude-routerv2 -> ROUTER_V2_FULL_TEST_OK
claude-routerv3 -> ROUTER_V3_FULL_TEST_OK
claude-routerv4 -> ROUTER_V4_FULL_TEST_OK
```

Current live listeners observed before writing this handover:

```text
8787: Python router v1
8791: Python router v2
8789: not currently listening
8792: not currently listening
```

This is okay. v3 and v4 can be started on demand.
