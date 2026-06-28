# FreeLLM Claude Code Router

A local gateway that lets **Claude Code** drive free / cheap alternate models through a **FreeLLMAPI** backend, with a multi-version routing engine, a live dashboard, storm-hardened fallback, and a self-improving skill optimizer.

> Runs Claude Code against your own FreeLLMAPI stack instead of the Anthropic API — translating Anthropic-format requests to OpenAI-compatible ones and picking the best model/strategy per request.

```bash
claude-routerv4   # auto meta-router: picks v1, v2, or v3 per request
```

---

## Credits

This project is **inspired by and builds on**:

- **[`musistudio/claude-code-router`](https://github.com/musistudio/claude-code-router)** — the original Claude Code routing fork that lets you decide how Claude Code interacts with the model. This repo's proxy layer and Anthropic↔OpenAI translation pattern derive from that work, extended here with multi-version routing, an ensemble mode, a live dashboard, and storm-hardened fallback.
- **[`karpathy/autoresearch`](https://github.com/karpathy/autoresearch)** — the self-improving research loop pattern applied in the bundled `autoresearch` optimizer and the reliability experiments.

All code in this repo is original to the FreeLLM Claude Code Router project unless otherwise noted in the file header.

---

## What it does

Claude Code expects Anthropic-style endpoints:

```
/v1/messages
/v1/messages/count_tokens
```

FreeLLMAPI exposes OpenAI-compatible endpoints:

```
/v1/chat/completions
/v1/responses
/v1/embeddings
```

This project inserts a local adapter:

```
Claude Code
  └── local Anthropic-compatible proxy  (this repo, port 8792)
        └── FreeLLMAPI  (OpenAI-compatible, port 3004)
              └── provider/model fallback inside FreeLLMAPI
```

### Why a router in front of a router?

FreeLLMAPI is *already* a router (it falls back across providers/models). So why another layer?

1. **Protocol translation** — Claude Code speaks Anthropic format; FreeLLMAPI speaks OpenAI format. This proxy translates in both directions.
2. **Capability awareness** — Claude Code needs models that support tool calls and large context windows. The proxy probes each model, builds an allowlist of *Claude-Code-compatible* models, and only routes to those.
3. **Context-aware tool pruning** — Claude Code injects MCP tool schemas under `<system-reminder>` blocks. The proxy strips these before evaluating, shrinking the tools payload by ~91% (324k → 27k chars) so requests fit in context.
4. **Strategy selection** — different requests benefit from different strategies (single fast model vs. multi-model ensemble). The v4 meta-router picks the right one per request.

---

## The Full Stack

To run this end-to-end you need four layers. This repo is **layer 2**.

### Layer 1 — FreeLLMAPI (backend, not in this repo)

An OpenAI-compatible API gateway you run on a server. It aggregates free/cheap model providers (OpenRouter free tiers, GitHub Models, Ollama Cloud, Azure, etc.) and exposes one unified `/v1` endpoint with its own provider fallback.

- **Role:** serves `/v1/chat/completions`, `/v1/models`
- **Port:** `3004` locally (SSH-tunneled from your server's `3001`)
- **Secret:** a unified API key stored in the server's SQLite DB — fetched over SSH by the launcher (see `.env.example`)
- **Dashboard:** `http://127.0.0.1:3004`

You provide your own FreeLLMAPI instance. See `HANDOVER.md` for how the SSH tunnel + key fetch works.

### Layer 2 — FreeLLM Claude Code Router (this repo)

The local proxy that Claude Code actually talks to.

- **Role:** Anthropic↔OpenAI translation, model allowlisting, multi-version routing, storm-hardened fallback, dashboard
- **Port:** `8792` (v4 auto mode; also `8787` v1, `8791` v2, `8789` v3)
- **Code:** `freellm_router_mvp.py` (single-file proxy + mock API + probe + smoke tests)
- **Secret:** reads `FREE_LLM_API_TOKEN` from `.env` (see `.env.example`)

### Layer 3 — Claude Code (the client)

Anthropic's official CLI coding agent. Pointed at the local proxy instead of `api.anthropic.com`:

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8792
claude
```

### Layer 4 — Autoresearch optimizer (optional, bundled)

A self-improving loop that stress-tests the router under real load, measures success rate + latency, and feeds findings back. Applies the [Karpathy autoresearch](https://github.com/karpathy/autoresearch) pattern to the router.

- **Code:** `autoresearch.py`, `experiment_harness.py`, `auto_optimizer.py`, `self_healing_daemon.py`
- **Runs:** `python3 autoresearch.py --skill hybrid-rag --cycles 10`

---

## Quick Start

### Prerequisites

- Python 3.10+ (stdlib only — no pip dependencies)
- A running FreeLLMAPI instance reachable over HTTP
- Claude Code CLI installed (`claude`)
- The unified FreeLLMAPI key (in `.env`)

### 1. Configure secrets

```bash
cp .env.example .env
# Edit .env and set FREE_LLM_API_TOKEN
```

### 2. Probe your FreeLLMAPI (build the model allowlist)

```bash
python3 freellm_router_mvp.py probe \
  --api-base http://127.0.0.1:3004/v1 \
  --auth-token "$FREE_LLM_API_TOKEN" \
  --output models.allowlist.real.json
```

This tests each model for basic chat, tool-call support, and context window, then writes the allowlist of Claude-Code-compatible models.

### 3. Start the proxy (v4 auto mode)

```bash
set -a; source .env; set +a
python3 freellm_router_mvp.py proxy \
  --api-base http://127.0.0.1:3004/v1 \
  --allowlist models.allowlist.real.json \
  --port 8792 \
  --mode v4 \
  --api-token "$FREE_LLM_API_TOKEN"
```

### 4. Point Claude Code at it

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8792
claude -p 'Say ROUTER_OK and nothing else.'
```

### 5. Or use the launcher wrapper

```bash
# Installs claude-router, claude-routerv1..v4 into ~/.local/bin
# Fetches the key over SSH, starts the proxy, launches claude
claude-routerv4
```

---

## Router Versions

Four experimental strategies, all selectable via one command:

| Command | Version | Strategy |
|---------|---------|----------|
| `claude-routerv1` | v1 | One selected compatible model |
| `claude-routerv2` | v2 | Task-aware policy router with ordered fallback across allowlisted models |
| `claude-routerv3` | v3 | Multi-advisor ensemble for text-only; falls back to v2 single-model when tools present |
| `claude-routerv4` | v4 | **Meta-router** — auto-selects v1/v2/v3 per request (recommended) |

### v4 auto-routing rules

The meta-router inspects the request and picks the strategy:

```
tools present             -> v2  (single driver model needed for tool calls)
very long context         -> v2
coding/fixing/debugging/  -> v2
  testing/review
compare/tradeoff/         -> v3  (ensemble benefits from multiple perspectives)
  brainstorm/synthesize/
  strategy/architecture
short simple request      -> v1
summary/overview         -> v2
fallback                 -> v2
```

Debug headers on every response:

```
x-router-mode
x-router-selected-version
x-router-selected-model
x-router-policy
x-router-route-reason
x-router-advisor-models
x-router-fallbacks
```

### v2 policies

v2 classifies requests into a deterministic policy and picks one model, falling back across compatible models on failure:

```
long-context
coding
review
summarization
fast
```

---

## Storm-Hardened Fallback

The fallback engine is what keeps success rate high under upstream rate-limit storms. Three design choices:

1. **Parallel first-attempt race** — all eligible models are raced in parallel; the first 200 wins. Happy-path latency ≈ one round trip, not N × timeout.
2. **Fail-fast on non-retryable errors** — HTTP 401/400/403/404 (auth, catalog, invalid request) mark a model dead instantly. No same-model retry.
3. **No same-model retry on 429** — free-tier rate limits are model-wide; retrying the same model seconds later still fails. The router moves to the next model, with at most one short global backoff if every model is rate-limited.

This turns a rate-limit storm from a 30–70s hang (the old 3×-per-model `time.sleep` loop) into ~one failed round trip, eliminating client-side broken pipes.

See `experiment_harness.py` to reproduce the stress test:

```bash
python3 experiment_harness.py --requests 50
```

---

## Live Dashboard

```
http://127.0.0.1:8792/dashboard
```

Shows live status, current mode, and the last 50 routing decisions with latency bars and error breakdown. The headline success-rate + avg-latency metrics are computed over the last 50 decisions.

JSON API:

```
GET /api/decisions   → {"decisions": [...last 50]}
GET /api/config      → {"mode": "v4"}
POST /api/config/update  {"mode": "v2"}
GET /health          → {"ok": true}
```

---

## Files

```
freellm_router_mvp.py          Main proxy: Anthropic↔OpenAI translation, routing, fallback, dashboard
experiment_harness.py          Stress-test harness (drives mixed traffic, reports success/latency)
auto_optimizer.py              Automated scenario optimizer
self_healing_daemon.py         Watches router_decisions.jsonl, self-corrects policies
autoresearch.py                Karpathy-pattern self-improving loop (in skills/research/autoresearch/)
run_integration_tests.py       Integration test suite
run_reliability_experiment.py  Reliability experiment runner
probe_real_freellmapi.sh       Regenerate the real allowlist
run_real_proxy.sh              Manual proxy runner

models.allowlist.example.json  Example allowlist (committed)
models.allowlist.real.json     Real probed allowlist (gitignored)
router_decisions.jsonl         Real request log (gitignored)

README.md                      This file
HANDOVER.md                    Operator handover (secrets scrubbed)
VERSION-1.md … VERSION-4.md    Per-version design notes
STARTUP-COST-ANALYSIS.md       Token-cost analysis of Claude Code startup
start-here.html                Clickable local map
```

### Secrets

All secrets live in `.env` (gitignored). See `.env.example` for the full list:

- `FREE_LLM_API_TOKEN` — your FreeLLMAPI unified key
- `FREE_LLM_API_BASE` — upstream base URL
- `CLAUDE_ROUTER_PORT`, `CLAUDE_ROUTER_MODE`

The launcher fetches the key over SSH if `.env` is empty:

```bash
ssh -o ClearAllForwardings=yes freellmapi-tunnel \
  "sqlite3 /opt/freellmapi/data/freeapi.db \"select value from settings where key='unified_api_key';\""
```

---

## Current Allowlisted Models

Probed against a live FreeLLMAPI instance. "Compatible" means: basic chat works, tool-call shape works, and context window is large enough for Claude Code startup/tool prompts.

| Model | Tools | Context | Roles |
|-------|:-----:|--------:|-------|
| `gpt-oss-120b` | ✅ | 131072 | coding, tool_use, summarization |
| `gpt-oss-20b` | ✅ | 131072 | coding, tool_use, summarization |
| `llama-3.3-70b` | ✅ | 131072 | coding, tool_use, summarization |
| `gpt-4.1` | ✅ | 128000 | coding, tool_use, summarization |
| `qwen/qwen3-coder:free` | ❌ | 8192 | coding, summarization |
| `gemini-2.5-flash` | ❌ | 1048576 | summarization |

FreeLLMAPI can still route/fallback underneath, so the requested model and the actual provider/model may differ.

---

## Testing

```bash
# Syntax check
python3 -m py_compile freellm_router_mvp.py
bash -n probe_real_freellmapi.sh run_real_proxy.sh

# Smoke test each version
for v in v1 v2 v3 v4; do
  claude-router$v -p "Say ROUTER_${v}_TEST_OK and nothing else." --output-format text
done

# Stress test v4 (auto mode)
python3 experiment_harness.py --requests 50

# Direct v4 route proof
curl -sS -D /tmp/h.headers http://127.0.0.1:8792/v1/messages \
  -H 'content-type: application/json' \
  -d '{"model":"gpt-oss-120b","max_tokens":30,"messages":[{"role":"user","content":"Compare tradeoffs."}]}' \
  > /dev/null
grep -i 'x-router-selected-version' /tmp/h.headers   # → v3
```

---

## Troubleshooting

### `No module named 'encodings'`

A broken `PYTHONHOME` / `PYTHONPATH` / `PYTHONEXECUTABLE` leaking into router startup. The launcher unsets these. Override Python if needed:

```bash
CLAUDE_ROUTER_PYTHON=/path/to/python3 claude-routerv4
```

### `Address already in use`

Another process holds the port. v2 uses 8791 and v4 uses 8792 because 8788/8790 were taken by node processes. Check listeners:

```bash
lsof -nP -iTCP:8792 -sTCP:LISTEN
```

### `All models exhausted` (429)

Upstream FreeLLMAPI rate limits hit. The storm-hardened fallback handles this by racing all models and failing fast. For sustained load you need higher-limit (paid) API keys in your FreeLLMAPI DB.

### Broken pipe (`[Errno 32]`)

Client (Claude Code) closed the connection before the proxy finished. Caused by old same-model retry loops holding connections 30–70s. The parallel-race fallback eliminates this.

---

## Design Notes

**Router-R1** (a learned decision model) is the planned future layer but is not yet integrated. Current routing is deterministic Python logic in `choose_model`, `classify_v2_policy`, `classify_v4_route`. The safe insertion point:

```
request
  -> hard compatibility filter  (eligible models only)
    -> Router-R1 chooses model or routing strategy
```

Router-R1 should only ever see models that passed compatibility checks for the current request — never the raw FreeLLMAPI model list.

---

## Recommended Next Steps

1. Automated integration test script running v1–v4 checks in one command
2. Small Python supervisor for start/stop/status (replacing bash + PID files)
3. JSONL route logs for historical inspection (already in `router_decisions.jsonl`)
4. Router-R1 decision layer once the deterministic router is stable
5. Browser UI page showing live status + recent decisions (the dashboard already does this)

---

## License

This project builds on [`musistudio/claude-code-router`](https://github.com/musistudio/claude-code-router) and the [`karpathy/autoresearch`](https://github.com/karpathy/autoresearch) pattern. See file headers for individual attribution. Provide credit to the upstream projects when forking.
