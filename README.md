# FreeLLM Claude Code Router

This experiment lets Claude Code run through your FreeLLMAPI stack.

The baseline command is:

```bash
claude-routerv1
```

The current meta-router command is:

```bash
claude-routerv4
```

There is also a clickable local map:

[start-here.html](./start-here.html)

Agent handover:

[HANDOVER.md](./HANDOVER.md)

## Simple Explanation

### Original FreeLLMAPI System

FreeLLMAPI is already a router.

Normally, an app talks to it like this:

```text
App
  -> FreeLLMAPI
    -> OpenRouter / Groq / Ollama / SambaNova / OpenCode / Cerebras / etc.
```

If the app sends:

```json
{ "model": "auto" }
```

FreeLLMAPI chooses a model.

If the app sends:

```json
{ "model": "qwen/qwen3-coder:free" }
```

FreeLLMAPI tries that model, but may still fall back if the model fails, rate-limits, or is unavailable.

So the original FreeLLMAPI system already handles:

```text
model selection
provider fallback
rate-limit handling
free-tier routing
```

### The Problem

Claude Code does not naturally speak FreeLLMAPI's API format.

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

So Claude Code and FreeLLMAPI do not plug together cleanly without an adapter.

### Our Adapted System

We added a local adapter/router in the middle:

```text
Claude Code
  -> local Claude router proxy
    -> FreeLLMAPI
      -> real model providers
```

The v1 local proxy runs here:

```text
http://127.0.0.1:8787
```

Other version ports:

```text
v2: http://127.0.0.1:8791
v3: http://127.0.0.1:8789
v4: http://127.0.0.1:8792
```

FreeLLMAPI runs here:

```text
http://127.0.0.1:3004/v1
```

So the adapted system is:

```text
Claude Code speaks Anthropic
  -> our proxy translates
    -> FreeLLMAPI speaks OpenAI-compatible
      -> free/cheap model providers answer
```

Before:

```text
Other apps -> FreeLLMAPI -> free models
```

Now:

```text
Claude Code -> our adapter -> FreeLLMAPI -> free models
```

### What `claude-routerv1` Does

When you run:

```bash
claude-routerv1
```

it:

1. Starts the local proxy if needed.
2. Points Claude Code at `http://127.0.0.1:8787`.
3. Gives Claude a concrete model name, currently `qwen/qwen3-coder:free`.
4. Converts Claude's Anthropic request into a FreeLLMAPI chat completion request.
5. Sends the request to FreeLLMAPI.
6. Lets FreeLLMAPI use the requested model or fall back.
7. Converts the answer back into Claude's expected format.

Important distinction:

```text
requested_model
  What our proxy asks FreeLLMAPI for.

actual model
  What FreeLLMAPI really used after fallback.
```

Example:

```text
requested_model: qwen/qwen3-coder:free
actual model: sambanova / gpt-oss-120b
```

That is normal. It means FreeLLMAPI's fallback system did its job.

## Mental Model

```text
You
  -> claude-routerv1
    -> Claude Code
      -> local Anthropic-compatible proxy on 127.0.0.1:8787
        -> FreeLLMAPI on 127.0.0.1:3004/v1
          -> OpenRouter / Groq / SambaNova / Ollama / OpenCode / Cerebras / etc.
```

Claude Code speaks Anthropic's Messages API. FreeLLMAPI speaks OpenAI-compatible APIs. The local proxy translates between them and decides which FreeLLMAPI model to request.

## Surfaces

| Surface | URL / Command | Purpose |
| --- | --- | --- |
| Claude launcher v1 | `claude-routerv1` | Start Claude through the v1 router |
| Generic launcher | `claude-router --mode v1` | Same as v1, mode-explicit |
| Local proxy | `http://127.0.0.1:8787` | Anthropic-compatible gateway for Claude |
| Proxy models | `http://127.0.0.1:8787/v1/models` | Shows allowlisted router models |
| FreeLLMAPI | `http://127.0.0.1:3004/v1` | OpenAI-compatible backend |
| FreeLLMAPI dashboard | `http://127.0.0.1:3004` | UI/dashboard through SSH tunnel |
| iframe proxy | `http://127.0.0.1:3014` | Dashboard-friendly proxy |

## Commands

Start Claude:

```bash
claude-routerv1
```

One-shot test:

```bash
claude-routerv1 -p 'Say ROUTER_V1_OK and nothing else.' --output-format text
```

Manage the local proxy:

```bash
claude-router --status
claude-router --start-proxy
claude-router --stop
claude-router --probe
```

Legacy aliases:

```bash
claude-router
claude-router-v1
claude-router --mode v1
```

## Version Overview

| Version | Command | Status | Behavior |
| --- | --- | --- | --- |
| v1 | `claude-routerv1` | Working | Single selected model request, FreeLLMAPI fallback underneath |
| v2 | `claude-routerv2` | Working | Task-aware routing policies like coding, fast, long-context |
| v3 | `claude-routerv3` | Working | Multi-model ensemble/orchestrator for text-only requests; safe single-model fallback for tool requests |
| v4 | `claude-routerv4` | Working | Meta-router that chooses v1, v2, or v3 per request |

## Version 1

Details: [VERSION-1.md](./VERSION-1.md)

Version 1 sends each Claude request to **one selected FreeLLMAPI model**.

```text
Claude request
  -> local proxy checks tools/context/allowlist
    -> selected requested model
      -> FreeLLMAPI
        -> provider fallback if needed
```

The launcher presents Claude Code with:

```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:8787
ANTHROPIC_MODEL=qwen/qwen3-coder:free
ANTHROPIC_SMALL_FAST_MODEL=qwen/qwen3-coder:free
```

Claude Code did not like the synthetic model name `router-auto`, so v1 presents a concrete allowlisted model. The local proxy can still choose behind the scenes.

## Requested Model vs Actual Model

There are two model names to understand.

```text
requested_model
  The model our proxy asks FreeLLMAPI to use.

actual model
  The provider/model FreeLLMAPI really used after fallback.
```

Example from a successful v1 test:

```text
requested_model: qwen/qwen3-coder:free
first attempt: openrouter / qwen/qwen3-coder:free -> 429
successful actual model: sambanova / gpt-oss-120b
```

This is expected. FreeLLMAPI is itself a router/fallback system.

## Current Allowlisted Models

The real allowlist lives in:

[models.allowlist.real.json](./models.allowlist.real.json)

Current tested candidates:

```text
qwen/qwen3-coder:free
gemini-2.5-flash
z-ai/glm-4.5-air:free
openai/gpt-oss-120b:free
openai/gpt-oss-20b:free
llama-3.3-70b-versatile
```

These are marked usable when they pass:

```text
basic chat
tool calls
context window large enough for Claude Code startup/tool prompts
```

FreeLLMAPI may still fallback to another provider/model at runtime.

## Files

| File | Purpose |
| --- | --- |
| [freellm_router_mvp.py](./freellm_router_mvp.py) | Python proxy, mock API, probe, and test harness |
| [probe_real_freellmapi.sh](./probe_real_freellmapi.sh) | Regenerate real allowlist from FreeLLMAPI |
| [run_real_proxy.sh](./run_real_proxy.sh) | Start proxy against FreeLLMAPI |
| [models.allowlist.real.json](./models.allowlist.real.json) | Real model compatibility allowlist |
| [models.allowlist.example.json](./models.allowlist.example.json) | Example allowlist |
| [VERSION-1.md](./VERSION-1.md) | v1 behavior and test details |
| [VERSION-2.md](./VERSION-2.md) | v2 task-aware routing details |
| [VERSION-3.md](./VERSION-3.md) | v3 ensemble routing details |
| [VERSION-4.md](./VERSION-4.md) | v4 meta-router details |
| [HANDOVER.md](./HANDOVER.md) | Full project context for another agent |
| [start-here.html](./start-here.html) | Clickable local map |

Installed commands:

```text
/Users/robinsverd/.local/bin/claude-router
/Users/robinsverd/.local/bin/claude-routerv1
/Users/robinsverd/.local/bin/claude-router-v1
/Users/robinsverd/.local/bin/claude-routerv2
/Users/robinsverd/.local/bin/claude-routerv3
/Users/robinsverd/.local/bin/claude-routerv4
```

## Fast Offline Test

This does not touch the real FreeLLMAPI. It uses a mock backend.

```bash
cd /Users/robinsverd/Thrivbe-AI/lab/freellm-router-mvp
python3 freellm_router_mvp.py smoke
```

Expected:

```text
Compatible models: free-code-tools
Smoke test passed.
```

## Real Probe

FreeLLMAPI is reachable at:

```text
http://127.0.0.1:3004/v1
```

Regenerate the real allowlist:

```bash
cd /Users/robinsverd/Thrivbe-AI/lab/freellm-router-mvp
./probe_real_freellmapi.sh
```

The scripts fetch the unified FreeLLMAPI key from the server database over `freellmapi-tunnel` unless `FREE_LLM_API_TOKEN` is already set.

## Troubleshooting

### `No module named 'encodings'`

If a router command fails with:

```text
Fatal Python error: Failed to import encodings module
ModuleNotFoundError: No module named 'encodings'
```

that usually means the shell has a broken `PYTHONHOME`, `PYTHONPATH`, or `PYTHONEXECUTABLE`.

The launcher now starts the router proxy with those variables removed, and defaults to `/usr/bin/python3` when available. To force another Python:

```bash
CLAUDE_ROUTER_PYTHON=/path/to/python3 claude-routerv2
```

## Router Versions

### v2: Task-Aware Router

Command:

```bash
claude-routerv2
```

Behavior:

```text
classify request -> choose policy -> choose one model from policy pool
```

Example policies:

```text
coding
fast
long-context
cheap
review
```

### v3: Ensemble Router

Command:

```bash
claude-routerv3
```

Behavior:

```text
classify request
  -> ask multiple FreeLLMAPI models
  -> aggregate/critique/synthesize
  -> return one final answer to Claude
```

For Claude Code safety, only one model should drive tool calls. Other models should act as advisors/critics.

Current v3 behavior:

```text
text-only request
  -> multiple advisor models
  -> aggregator model
  -> one final response

tool-bearing request
  -> safe v2 single-model route
```

### v4: Meta-Router

Command:

```bash
claude-routerv4
```

Behavior:

```text
classify request
  -> choose v1, v2, or v3
  -> run the chosen router strategy
  -> return one final response to Claude
```

Current v4 choices:

```text
simple short request -> v1
coding/review/tools/long-context -> v2
strategy/comparison/synthesis text-only request -> v3
```

Details: [VERSION-4.md](./VERSION-4.md)

## Router-R1

Router-R1 can eventually replace the deterministic `choose_model(...)` decision step.

Safe insertion point:

```text
hard compatibility filter
  -> eligible models only
    -> Router-R1 chooses from eligible set
```

Router-R1 should not choose from the raw FreeLLMAPI model list. It should only see models that passed compatibility checks for the current request.
