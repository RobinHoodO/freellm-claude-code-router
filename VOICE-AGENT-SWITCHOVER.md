# Voice Agent Router — Switch-Over Guide

How to point the **Thrivbe Voice Agent (Rachel)** at the speed-first voice router
instead of calling FreeLLMAPI directly.

---

## What changes (and what doesn't)

**Before** — the voice agent calls FreeLLMAPI directly:

```
server.py  →  http://localhost:3004/v1/chat/completions   (FreeLLMAPI, "auto" model)
```

**After** — the voice agent calls the voice router, which calls FreeLLMAPI:

```
server.py  →  http://localhost:8793/v1/chat/completions   (voice router, speed-first)
                  →  http://localhost:3004/v1             (FreeLLMAPI)
```

The voice router is OpenAI-format native (no Anthropic translation), so `server.py`
needs **only one line changed** — the `API_URL`. No other code changes.

---

## Why a separate router for the voice agent

The Claude Code router (`freellm_router_mvp.py`, port 8792) is optimized for
**intelligence** — it picks the strongest model per task (`mistral-large-3-675b`,
a 675B model that takes 2–9s). The voice agent has the opposite need: **latency is
king** — it must feel conversational (<3s to first byte), and most requests carry
tools (phone control, CRM, search).

So the voice router (`voice_router_mvp.py`, port 8793) optimizes for **speed**:

| Request shape | Policy | Model picked (in order) |
|---|---|---|
| Tools present (most voice reqs) | `tools` | `llama-3.3-70b` → `gpt-oss-20b` → `gpt-4.1` → `mistral-large-3-675b` |
| Plain short chat | `fast` | `gpt-oss-20b` → `llama-3.3-70b` → `gpt-4.1` |
| Explicit reasoning/compare | `reasoning` | `mistral-large-3-675b` → `gpt-4.1` → `llama-3.3-70b` |
| Long context (>60k tokens) | `long-context` | `nemotron-3-super-120b` (1M ctx) |
| Summarization | `summarization` | `gpt-4.1` → `mistral-large-3-675b` |

Plus storm-hardened fallback: try the preferred (fastest) model first; on failure
race the rest in parallel; fail-fast on 401/400/429 so a rate-limit storm doesn't
turn into a 30–70s hang.

---

## Switch-over (one line in server.py)

In `lab/voice-agent/server.py`, change:

```python
# BEFORE — direct to FreeLLMAPI
API_URL = "http://localhost:3004/v1/chat/completions"
```

to:

```python
# AFTER — through the speed-first voice router
API_URL = "http://localhost:8793/v1/chat/completions"
```

That's it. `API_KEY`, `DEFAULT_MODEL`, `TOOLS`, `SYSTEM_PROMPT`, the tool-calling
loop — all unchanged. The router accepts whatever model the client sends (it ignores
it and picks the right one itself), and passes the OpenAI request/response through
unchanged.

---

## Deploy on the Hetzner server

The voice agent runs on `thrivbe-1` (Hetzner) and talks to `localhost:3004`
(FreeLLMAPI is on the same box). So the voice router must run there too.

### 1. Copy the router to the server

```bash
# from your Mac
scp /Users/robinsverd/Thrivbe-AI/lab/freellm-router-mvp/voice_router_mvp.py \
    /Users/robinsverd/Thrivbe-AI/lab/freellm-router-mvp/models.allowlist.real.json \
    hetzner:/opt/voice-bridge/
```

### 2. Create a systemd service

```bash
ssh hetzner 'sudo tee /etc/systemd/system/voice-router.service' <<'UNIT'
[Unit]
Description=Thrivbe Voice Router (speed-first)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/voice-bridge
Environment=FREE_LLM_API_TOKEN=freellmapi-6b5113545450f34f4dbceb678e823e87ca980447d2a44478
Environment=FREE_LLM_API_BASE=http://localhost:3004/v1
ExecStart=/usr/bin/python3 /opt/voice-bridge/voice_router_mvp.py proxy \
  --api-base http://localhost:3004/v1 \
  --allowlist /opt/voice-bridge/models.allowlist.real.json \
  --port 8793 \
  --api-token ${FREE_LLM_API_TOKEN}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
```

> **Security:** put the real token in `/opt/voice-bridge/.env` or a systemd
> `EnvironmentFile=` instead of hardcoding it. See `.env.example`.

### 3. Enable + start

```bash
ssh hetzner 'sudo systemctl daemon-reload && sudo systemctl enable --now voice-router'
ssh hetzner 'systemctl status voice-router --no-pager'
ssh hetzner 'curl -s http://localhost:8793/health'
# → {"ok": true, "router": "voice", "mode": "speed-first"}
```

### 4. Point server.py at it

Edit `/opt/voice-bridge/server.py` on the server:

```python
API_URL = "http://localhost:8793/v1/chat/completions"
```

Then restart the voice bridge:

```bash
ssh hetzner 'sudo systemctl restart voice-bridge'
ssh hetzner 'journalctl -u voice-bridge -f -n 50'   # watch it work
```

---

## Verifying it works

```bash
# 1. Router health
curl -s http://localhost:8793/health

# 2. Dashboard (last 50 routing decisions)
open http://localhost:8793/dashboard        # or http://hetzner.tail9908c7.ts.net:8793/dashboard

# 3. Decision log
tail -f /opt/voice-bridge/router_decisions_voice.jsonl

# 4. Send a voice-agent-style request through it
curl -s http://localhost:8793/v1/chat/completions \
  -H 'content-type: application/json' \
  -H "authorization: Bearer $FREE_LLM_API_TOKEN" \
  -d '{"model":"auto","max_tokens":80,"messages":[{"role":"user","content":"Hey Rachel, call mom."}],"tools":[{"type":"function","function":{"name":"call","description":"call","parameters":{"type":"object","properties":{"number":{"type":"string"}}}}}]}' \
  | python3 -m json.tool
```

Check the `x-router-selected-model` and `x-router-policy` headers to confirm it's
picking the fast tool-capable model (`llama-3.3-70b`) for tool-bearing requests.

---

## Rollback

To revert, change `API_URL` back to `http://localhost:3004/v1/chat/completions`
and restart `voice-bridge`. The router can stay running (it's harmless) or be
stopped with `sudo systemctl stop voice-router`.

---

## Notes

- **No streaming yet.** `server.py` does `r.json()` on the full response, so the
  router returns the full JSON (non-streaming). The router's streaming code is
  dormant and only activates if a client sends `stream:true`. To enable streaming
  later, `server.py` would need to consume the SSE stream and buffer it to text
  before handing to ElevenLabs — a small future change for an extra latency win.
- **Same allowlist** as the Claude Code router (`models.allowlist.real.json`). If
  you probe new models, both routers pick them up automatically.
- **Separate decision log** (`router_decisions_voice.jsonl`) so voice traffic
  doesn't pollute the Claude Code router's dashboard.
