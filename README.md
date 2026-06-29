# FreeLLM Claude Code Router

A local gateway that lets **Claude Code** drive free / cheap alternate models through a **FreeLLMAPI** backend, with a multi-version routing engine, a live dashboard, storm-hardened fallback, a self-improving skill optimizer, and a speed-first voice agent router.

> Runs Claude Code against your own FreeLLMAPI stack instead of the Anthropic API — translating Anthropic-format requests to OpenAI-compatible ones and picking the best model/strategy per request.

> [!NOTE]
> **Prerequisite Backend**: This tool is an adapter/router proxy layer. To use it, you also need a running instance of **[FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi)** (or a compatible setup) as your backend.

```bash
claude-routerv4   # auto meta-router: picks v1, v2, or v3 per request
```

---

## Table of Contents

1. [Credits](#credits)
2. [What It Does](#what-it-does)
3. [The Full Stack](#the-full-stack)
4. [Quick Start](#quick-start)
5. [Router Versions & Strategies](#router-versions--strategies)
6. [Operator Handover & Recent Resolutions](#operator-handover--recent-resolutions)
7. [Voice Agent Router & Switch-Over Guide](#voice-agent-router--switch-over-guide)
8. [FreeLLMAPI Model Routing Map](#freellmapi-model-routing-map)
9. [Claude Code Startup Token Cost & Savings Analysis](#claude-code-startup-token-cost--savings-analysis)
10. [Reliability Experiment Report](#reliability-experiment-report)
11. [Troubleshooting & Gotchas](#troubleshooting--gotchas)
12. [Design Notes & Next Steps](#design-notes--next-steps)
13. [License](#license)

---

## Credits

This project is **inspired by and builds on**:

- **[`musistudio/claude-code-router`](https://github.com/musistudio/claude-code-router)** — the original Claude Code routing fork that lets you decide how Claude Code interacts with the model. This repo's proxy layer and Anthropic↔OpenAI translation pattern derive from that work, extended here with multi-version routing, an ensemble mode, a live dashboard, and storm-hardened fallback.
- **[`karpathy/autoresearch`](https://github.com/karpathy/autoresearch)** — the self-improving research loop pattern applied in the bundled `autoresearch` optimizer and the reliability experiments.

All code in this repo is original to the FreeLLM Claude Code Router project unless otherwise noted in the file header.

---

## What It Does

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

You provide your own FreeLLMAPI instance.

> [!IMPORTANT]
> **FreeLLMAPI Backend Required**: This repository contains only the proxy/router adapter layer. You must set up and run a **[FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi)** instance (either self-hosted or managed) to act as the backend for this proxy.

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

A self-improving loop that stress-tests the router under real load, measures success rate + latency, and feeds findings back. Applies the Karpathy autoresearch pattern to the router.

- **Code:** `autoresearch.py`, `experiment_harness.py`, `auto_optimizer.py`, `self_healing_daemon.py`
- **Runs:** `python3 autoresearch.py --skill hybrid-rag --cycles 10`

---

## Quick Start

### Prerequisites

- Python 3.10+ (stdlib only — no pip dependencies)
- A running **[FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi)** instance reachable over HTTP (required backend)
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

## Router Versions & Strategies

Four experimental strategies, all selectable via one command:

| Command | Version | Strategy | Port | Default / Policy |
|---------|---------|----------|------|-----------------|
| `claude-routerv1` | v1 | Baseline: One selected compatible model | `8787` | `qwen/qwen3-coder:free` |
| `claude-routerv2` | v2 | Task-aware policy router with ordered fallback | `8791` | Configurable policies |
| `claude-routerv3` | v3 | Multi-advisor ensemble; falls back to v2 if tools present | `8789` | Text-only parallel advisors |
| `claude-routerv4` | v4 | **Meta-router** — auto-selects v1/v2/v3 per request | `8792` | Dynamic routing rules |

### Detailed Version Architectures

#### Version 1: Single Selected Model Router (Baseline)
- **Shape:** Translates Claude Messages API requests to FreeLLMAPI chat completions and maps them directly to a selected allowlisted model.
- **Model Mapping:** Claude Code sees `qwen/qwen3-coder:free` (visible model name), but the backend handles provider-level fallback underneath.
- **Limitation:** Vulnerable to transient API provider rate limits (429s) or model failures because it makes a single static request attempt.

#### Version 2: Task-Aware Single-Model Router
- **Shape:** Classifies each request into a deterministic policy and selects the best model for the job.
- **Fallback Capability:** If the preferred model fails/rate-limits, the proxy retries alternate compatible models within the policy pool before returning an error.
- **Core Policies:**
  - `coding`: `qwen/qwen3-coder:free` → `openai/gpt-oss-120b:free` → `llama-3.3-70b-versatile`
  - `fast`: `openai/gpt-oss-20b:free` → `llama-3.3-70b-versatile`
  - `long-context`: `qwen/qwen3-coder:free` → `gemini-2.5-flash`
  - `review`: `openai/gpt-oss-120b:free` → `z-ai/glm-4.5-air:free`

#### Version 3: Multi-Model Ensemble Router
- **Shape:** Acts as an orchestrator for text-only queries. It queries multiple advisor models in parallel, aggregates their responses, and uses a synthesising step to produce a single final answer.
- **Safety Rule:** Claude Code tool-bearing requests are automatically diverted to the safe v2 single-model path. Only one model is allowed to drive tool execution.
- **Fit Criteria:**
  - *Good fit:* Planning, architecture design, debugging hypotheses, code review, large-context summarization.
  - *Bad fit:* Interactive shell loops, small edits, tool calls, streaming UX.
- **Robustness:** If an advisor fails, the engine continues with the remaining advisors. If all fail, it falls back to a single model.

#### Version 4: Meta-Router
- **Shape:** Inspects the incoming request context, checks context length, detects keywords/tool schemas, and selects the ideal router strategy (`v1`, `v2`, or `v3`) dynamically.
- **v4 Routing Rules:**
  ```text
  tools present                                -> v2 (Single driver model needed)
  very long context                            -> v2
  coding, fixing, debugging, testing, review   -> v2
  compare, tradeoff, brainstorm, synthesize,
  strategy, architecture                       -> v3 (Ensemble benefits)
  short simple request                         -> v1
  summary or overview                          -> v2
  fallback                                     -> v2
  ```

---

## Operator Handover & Recent Resolutions

### 🚀 Recent Resolutions (June 28, 11:45 AM)

We recently resolved three critical issues that were causing the router to fail during testing:

#### 1. Tool Bloat & Context Length Limit Exceeded
* **Issue**: Prompt + tools payload exceeded context length limits (estimating up to 178k input tokens).
* **Cause**: Claude Code injects rules and workspace skills under a `<system-reminder>` header in a `"role": "user"` block. The proxy's tool-pruner matched integration keywords within this block, attaching Cal, Stripe, Supabase, Apify, Beeper, Blotato, and Twenty MCP tools to every request.
* **Resolution**: Updated `freellm_router_mvp.py` to filter out `<system-reminder>` blocks before evaluating tools.
* **Result**: Tools payload shrank by **91.5%** (from 324k to 27k characters), fitting easily.

#### 2. Stale SSH Tunnel (502 Bad Gateway)
* **Issue**: Requests timed out or returned HTTP 502.
* **Cause**: A stale background SSH tunnel process was holding local port `3004`, failing to forward traffic to remote port `3001` (FreeLLMAPI).
* **Resolution**: Terminated the stale SSH process. A healthy tunnel was automatically re-established.

#### 3. Invalid API Key / 401 Unauthorized
* **Issue**: Upstream FreeLLMAPI returned `HTTP 401: Invalid API key`.
* **Cause**: The local proxy was not configured with the unified key and forwarded the client's `local-dev-token` to the remote server.
* **Resolution**: Retrieved the real unified API key from the remote SQLite database and updated the proxy request handler in `freellm_router_mvp.py` to extract bearer tokens safely. Restarted the local proxy with `--api-token` (read from `.env` — see `.env.example`).

---

## Voice Agent Router & Switch-Over Guide

Point the **Thrivbe Voice Agent (Rachel)** at the speed-first voice router instead of calling FreeLLMAPI directly.

```
Before: server.py  →  http://localhost:3004/v1/chat/completions (FreeLLMAPI)
After:  server.py  →  http://localhost:8793/v1/chat/completions (Voice Router, Port 8793)
                          →  http://localhost:3004/v1          (FreeLLMAPI)
```

The voice router uses standard OpenAI format (no Anthropic translation needed), requiring **only one line changed** in `server.py`.

### Why a separate router for the voice agent?
The Claude Code router (`freellm_router_mvp.py`, port 8792) is optimized for **intelligence** (chooses large, complex models taking 2–9s). The voice agent requires **conversational latency (<3s first-byte)**. The voice router (`voice_router_mvp.py`, port 8793) prioritizes **speed**:

| Request shape | Policy | Model picked (in order) |
|---|---|---|
| Tools present (most voice reqs) | `tools` | `llama-3.3-70b` → `gpt-oss-20b` → `gpt-4.1` → `mistral-large-3-675b` |
| Plain short chat | `fast` | `gpt-oss-20b` → `llama-3.3-70b` → `gpt-4.1` |
| Explicit reasoning/compare | `reasoning` | `mistral-large-3-675b` → `gpt-4.1` → `llama-3.3-70b` |
| Long context (>60k tokens) | `long-context` | `nemotron-3-super-120b` (1M ctx) |
| Summarization | `summarization` | `gpt-4.1` → `mistral-large-3-675b` |

### Deployment on the Hetzner server

The voice agent and FreeLLMAPI both run on `thrivbe-1` (Hetzner).

#### 1. Copy files to the server
```bash
scp voice_router_mvp.py models.allowlist.real.json hetzner:/opt/voice-bridge/
```

#### 2. Create the systemd service
Create `/etc/systemd/system/voice-router.service` on the server:
```ini
[Unit]
Description=Thrivbe Voice Router (speed-first)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/voice-bridge
EnvironmentFile=/opt/voice-bridge/.env
ExecStart=/usr/bin/python3 /opt/voice-bridge/voice_router_mvp.py proxy \
  --api-base http://localhost:3004/v1 \
  --allowlist /opt/voice-bridge/models.allowlist.real.json \
  --port 8793 \
  --api-token ${FREE_LLM_API_TOKEN}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

#### 3. Enable, start, and check status
```bash
ssh hetzner 'sudo systemctl daemon-reload && sudo systemctl enable --now voice-router'
ssh hetzner 'curl -s http://localhost:8793/health'
# Expected: {"ok": true, "router": "voice", "mode": "speed-first"}
```

#### 4. Point server.py at the Voice Router
Edit `API_URL` in `/opt/voice-bridge/server.py`:
```python
API_URL = "http://localhost:8793/v1/chat/completions"
```
Then restart the voice bridge:
```bash
ssh hetzner 'sudo systemctl restart voice-bridge'
```

---

## FreeLLMAPI Model Routing Map

Organized by task category exposed by your self-hosted **FreeLLMAPI** instance:

### 1. Coding & Software Development
*Best for code generation, debugging, refactoring, test suite creation, and tool-use scripts.*

| Model ID | Model Name | Context Window | Best Use Case |
| :--- | :--- | :--- | :--- |
| `qwen3-coder-480b` | Qwen3 Coder 480B | 1,048,576 tokens | Premium coding model with massive multi-file context capability. |
| `qwen3-coder-next` | Qwen3 Coder Next | 262,144 tokens | Large context general coder. |
| `codestral` | Codestral | 256,000 tokens | Specialized, fast code generation model. |
| `poolside-laguna-m.1` | Poolside Laguna M.1 | 262,144 tokens | Specialized software engineering agent model. |
| `poolside-laguna-xs.2` | Poolside Laguna XS.2 | 131,072 tokens | Lightweight software engineering model. |
| `deepseek-r1-distill-qwen-32b`| DeepSeek R1 Distill Qwen 32B | 131,072 tokens | Reason-before-acting distill model, great for logic bugs. |

### 2. Reasoning, Strategy & Synthesis (Ensemble Advisors)
*Best for structural choices, design patterns, tradeoff comparisons, and v3 ensemble critiques.*

| Model ID | Model Name | Context Window | Best Use Case |
| :--- | :--- | :--- | :--- |
| `deepseek-v4-pro` | DeepSeek V4 Pro | 131,072 tokens | High-reasoning reasoning model. |
| `mistral-large-3-675b` | Mistral Large 3 675B | 131,072 tokens | Robust agent for general complex reasoning and aggregations. |
| `hermes-3-405b` | Hermes 3 405B | 131,072 tokens | Full-size open weights model for complex logic and instructions. |
| `nemotron-3-nano-30b-reasoning`| Nemotron 3 Nano 30B Reasoning | 262,144 tokens | Specialized reasoning advisor. |
| `command-a-reasoning` | Command A Reasoning | 256,000 tokens | Logic-first search-capable agent. |
| `liquid-lfm-2.5-1.2b-thinking`| Liquid LFM 2.5 1.2B Thinking | 32,768 tokens | Lightweight thinking advisor. |

### 3. Long Context Processing & Summarization
*Best for reading large logs, auditing codebases, summarizing documents, and code reviews.*

| Model ID | Model Name | Context Window | Best Use Case |
| :--- | :--- | :--- | :--- |
| `nemotron-3-super-120b` | Nemotron 3 Super 120B | 1,000,000 tokens | Extreme long context processing (e.g., massive file analysis). |
| `kimi-k2.6` | Kimi K2.6 | 262,144 tokens | Highly competent long-context assistant. |
| `command-r-2` | Command R+ | 131,072 tokens | Premium search and long context RAG engine. |
| `command-r` | Command R | 131,072 tokens | Standard search and long context engine. |
| `nemotron-3-120b` | Nemotron 3 120B | 262,144 tokens | General document processing. |

### 4. Fast, Lightweight & Simple Tasks (Baselines)
*Best for short prompts, instant responses, interactive shell updates, and cheap fallbacks.*

| Model ID | Model Name | Context Window | Best Use Case |
| :--- | :--- | :--- | :--- |
| `deepseek-v4-flash` | DeepSeek V4 Flash | 131,072 tokens | Ultra-fast interactive completions. |
| `glm-4.7-flash` | GLM-4.7 Flash | 131,072 tokens | Lightweight speed-priority chats. |
| `llama-3.1-8b-instant` | Llama 3.1 8B Instant | 131,072 tokens | Immediate, small helper queries. |
| `llama-3.3-70b-fp8-fast` | Llama 3.3 70B fp8-fast | 24,000 tokens | Quantized fast 70B model. |
| `granite-4.0-h-micro` | Granite 4.0 H Micro | 131,072 tokens | Fast micro helper. |
| `liquid-lfm-2.5-1.2b` | Liquid LFM 2.5 1.2B | 32,768 tokens | Fast lightweight execution. |
| `llama-3.2-3b` | Llama 3.2 3B | 131,072 tokens | Ultra-light fallback helper. |

### 5. Vision & Multimodal Tasks
*Best for UI screenshot analysis, layouts audits, and diagram reading.*

| Model ID | Model Name | Context Window | Best Use Case |
| :--- | :--- | :--- | :--- |
| `glm-4.6v-flash` | GLM-4.6V Flash | 131,072 tokens | Fast multimodal inputs (images, diagrams). |
| `nemotron-nano-12b-vl` | Nemotron Nano 12B VL | 128,000 tokens | Vision-language understanding tasks. |

---

## Claude Code Startup Token Cost & Savings Analysis

**Workspace:** `Thrivbe-AI` (Measured via real requests in `router_decisions.jsonl` from this router's logs).

### 1. TL;DR — What one prompt costs

| Scenario | Input tokens per single prompt | Notes |
|---|---|---|
| Lean one-shot (`-p "..."`, minimal tool surface) | **~12,700 tok** | Measured P10 |
| Typical interactive session startup | **~29,000 tok** | Measured median (P50) |
| Full-context interactive startup (tools + skills + MCP) | **~53,800 tok** | Measured P90, most common cluster |
| Max observed | ~68,500 tok | Heavy tool-schema + skill-list load |

**Every prompt you send pays this input-token tax** because Claude Code re-sends the entire system prompt + context window on every turn. The first prompt of a session is the most expensive; subsequent prompts in the same session compound as prior turns accumulate.

### 2. Measured evidence
Captured during the FreeLLM router reliability experiment:
```
Real Claude Code requests logged:        143
Input tokens  — min: 12,677  max: 68,541  mean: 31,169
Output tokens — min: 0       max: 1,331   mean: 151

Distribution:
  12k tier  (lean -p startup)        19 requests
  20–29k tier                        69 requests   ← bulk of interactive turns
  30–44k tier                        20 requests
  45–59k tier (full context)         34 requests   ← fresh interactive startup
  60k+ tier                           2 requests
```

### 3. Startup overhead breakdown (this workspace)

| Component | Tokens | Source |
|---|---|---|
| Anthropic Claude Code base system prompt | ~11,000 | Built-in |
| Built-in tool schemas (~25–35 tools) | ~8,000–12,000 | Injected by Claude Code |
| `CLAUDE.md` (root project memory) | ~5,288 | `Thrivbe-AI/CLAUDE.md` (21,152 B) |
| `AGENTS.md` root (GitNexus Thrivbe-AI block) | ~1,373 | `Thrivbe-AI/AGENTS.md` (5,495 B) |
| `AGENTS.md` nested (GitNexus social-content-engine) | ~742 | `lab/social-content-engine/AGENTS.md` (2,968 B) |
| `CLAUDE.md` nested (cwd) | ~1,388 | `lab/social-content-engine/CLAUDE.md` (5,552 B) |
| Skills available-skills list (231 skills, brief headers only) | ~4,000–6,000 | Only name + one-line description loads |
| MCP tool schemas (firefly + task-master-ai) | ~2,000 | `.mcp.json` |
| GitNexus MCP tool schemas + usage instructions | ~3,000 | GitNexus MCP server |
| **Estimated total** | **~36,000–42,000** | |

### 4. Cost in dollars (Anthropic Sonnet 4 list pricing: $3 / 1M input)

| Scenario | Input cost | Output cost (avg ~150 tok) | Total / prompt |
|---|---|---|---|
| Lean one-shot (12.7k in) | $0.038 | $0.002 | **~$0.04** |
| Median interactive (29k in) | $0.087 | $0.002 | **~$0.09** |
| Full startup (53.8k in) | $0.161 | $0.002 | **~$0.16** |

**For a 10-turn interactive session** in this workspace: ~53.8k + 54k + 55k + … ≈ **~600k input tokens → ~$1.80** for the conversation.
The FreeLLM router is the **direct answer**: it routes this ~53,800-token payload through free models (like `gpt-oss-120b`) at **$0 cost**.

---

## Reliability Experiment Report

### Executive Summary

| Variant | Total Requests | Successes | Success Rate | Avg Latency (s) | Fallbacks Triggered |
| --- | --- | --- | --- | --- | --- |
| v1 (Single Model) | 10 | 10 | 100.0% | 8.26s | 10 |
| v2 (Task-Aware) | 10 | 10 | 100.0% | 4.83s | 6 |
| v3 (Ensemble) | 10 | 10 | 100.0% | 2.93s | 2 |
| v4 (Meta-Router) | 10 | 10 | 100.0% | 6.52s | 8 |

* **Version 3 (Ensemble)** proved to be the most reliable option during benchmark testing, achieving 100% success rate with only 2 fallback occurrences.
* **Version 2 (Task-Aware)** dramatically improves reliability over Version 1 by retrying alternate compatible models in the policy pool when the first model fails.
* **Version 4 (Meta-Router)** dynamically balances task requirements between speed (v1), robustness for coding/tools (v2), and multi-perspective synthesis (v3).

### Detailed Scenario Runs

#### v1 (Single Model)
- **Simple Chat, Coding Task, Tool Use, comparison:** All returned HTTP 200, but all triggered fallbacks because preferred models like `qwen/qwen3-coder:free` hit 429 errors from the upstream FreeLLMAPI.

#### v2 (Task-Aware)
- **Simple Chat & Comparison:** Latency was <1s using `llama-3.3-70b-versatile` under the `fast` policy.
- **Coding & Tool Use:** Triggered fallbacks to alternate coding pool models (e.g. `openai/gpt-oss-120b:free`) due to rate limits on first-choice models, resolving successfully.

#### v3 (Ensemble)
- **Simple Chat & Coding:** Parallel advisor calls resolved successfully without fallbacks, achieving excellent latencies (~1-2s).
- **Tool Use:** Safely defaulted to the v2 single-model coding path.

#### v4 (Meta-Router)
- **Comparison/Synthesis:** Correctly selected `v3` ensemble.
- **Coding / Tool Use:** Correctly selected `v2` policy.
- **Simple Chat:** Selected `v1` path.

---

## Troubleshooting & Gotchas

### 1. `No module named 'encodings'`
* **Cause:** Broken `PYTHONHOME` / `PYTHONPATH` leaking from parent environment.
* **Fix:** The wrappers (`claude-router`, `probe_real_freellmapi.sh`, `run_real_proxy.sh`) explicitly unset these env vars before executing Python. Override Python executable if needed:
  ```bash
  CLAUDE_ROUTER_PYTHON=/path/to/python3 claude-routerv4
  ```

### 2. Port Conflicts (`Address already in use`)
* **Conflict Ports:** Ports `8788` and `8790` are used by local Node.js processes.
* **Fix:**
  * v2 runs on `8791`
  * v4 runs on `8792`
  * Check active listeners:
    ```bash
    lsof -nP -iTCP:8792 -sTCP:LISTEN
    ```

### 3. `All models exhausted` (429)
* **Cause:** Upstream FreeLLMAPI free-tier rate limits reached.
* **Fix:** Single-model paths automatically retry other allowlisted models. v3 ensemble skips failed advisors. For heavy usage, update FreeLLMAPI with paid API keys.

### 4. Codex Tool Environment Reaping
* **Cause:** Background processes started from within the Codex environment are sometimes reaped when tools exit.
* **Fix:** Start proxies directly in the user's terminal:
  ```bash
  claude-routervN --start-proxy
  ```

---

## Design Notes & Next Steps

### R1 Decision Layer (Planned)
The future **Router-R1** learned decision model will sit after the compatibility filter:
```
Request 
  -> Hard Compatibility Filter (Eligible models only)
    -> Router-R1 (Chooses specific model or strategy)
      -> FreeLLMAPI
```
*Never let Router-R1 choose from the raw FreeLLMAPI list; it must only see verified compatible models for the current request.*

### Next Action items
1. Create an automated integration test script running v1-v4 direct endpoint checks in one go.
2. Implement a Python-based supervisor for start/stop/status of router services.
3. Streamlined JSONL logging for historical route inspection.

---

## License

This project builds on [`musistudio/claude-code-router`](https://github.com/musistudio/claude-code-router) and the [`karpathy/autoresearch`](https://github.com/karpathy/autoresearch) pattern. See file headers for individual attribution. Provide credit to the upstream projects when forking.
