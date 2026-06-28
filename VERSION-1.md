# Version 1: Single Selected Model Router

Version 1 is the baseline router.

## Shape

```text
Claude Code
  -> local Anthropic-compatible proxy
    -> choose one compatible FreeLLMAPI model
      -> FreeLLMAPI /v1/chat/completions
        -> provider/fallback underneath
```

## What It Does

- Translates Claude Messages API requests to FreeLLMAPI chat completions.
- Filters models by compatibility:
  - tool support
  - context window
  - allowlist probe result
- Sends each Claude request to one selected FreeLLMAPI model.
- Lets FreeLLMAPI handle provider-level fallback.

## Current Launcher Model

Claude Code is launched with:

```text
ANTHROPIC_MODEL=qwen/qwen3-coder:free
ANTHROPIC_SMALL_FAST_MODEL=qwen/qwen3-coder:free
```

This is the model name Claude Code sees. FreeLLMAPI may still serve another actual provider/model after fallback.

## Last Verified Behavior

Test:

```bash
claude-routerv1 -p 'Say ROUTERV1_COMMAND_OK and nothing else.' --output-format text
```

Result:

```text
ROUTERV1_COMMAND_OK
```

Backend example:

```text
requested_model: qwen/qwen3-coder:free
first attempt: openrouter / qwen/qwen3-coder:free -> 429
successful actual model: sambanova / gpt-oss-120b
```

## What It Does Not Do

- No multi-model ensemble.
- No response aggregation.
- No debate/critic model.
- No Router-R1 decision model yet.

## Run

```bash
claude-routerv1
```

Equivalent:

```bash
claude-router --mode v1
```

Legacy alias:

```bash
claude-router-v1
```

## Test

```bash
claude-routerv1 -p 'Say ROUTER_V1_OK and nothing else.' --output-format text
```

## Logs

Check launcher/proxy status:

```bash
claude-routerv1 --status
```

Check FreeLLMAPI actual backend models:

```bash
ssh -o ClearAllForwardings=yes freellmapi-tunnel \
  "sqlite3 -header -column /opt/freellmapi/data/freeapi.db \
  \"SELECT datetime(created_at, '+2 hours') AS oslo_time, platform, model_id, status, input_tokens, output_tokens, latency_ms, requested_model FROM requests ORDER BY id DESC LIMIT 10;\""
```
