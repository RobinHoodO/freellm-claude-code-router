# Version 4: Meta-Router

Status: working experiment.

Version 4 does not only choose a model. It chooses which router strategy to use:

```text
Claude request
  -> v4 meta-router
    -> choose v1, v2, or v3
      -> chosen router strategy chooses model(s)
        -> FreeLLMAPI
```

## What It Chooses

```text
v1
  Simple baseline route.
  One selected model request.

v2
  Task-aware single-model route.
  Best for Claude Code tool use, coding, review, debugging, and long context.

v3
  Multi-model ensemble route.
  Best for text-only strategy, comparison, brainstorming, and synthesis.
```

## Safety Rule

Tool-bearing Claude Code requests are routed to v2.

```text
Claude tools present
  -> v4 chooses v2
```

Only one model should drive tool calls. v3 remains available for text-only ensemble work.

## Routing Rules

Current deterministic rules:

```text
tools present
  -> v2

very long context
  -> v2

coding, fixing, debugging, testing, review
  -> v2

compare, tradeoff, best approach, brainstorm, synthesize, strategy, architecture
  -> v3

short simple request
  -> v1

summary or overview
  -> v2

fallback
  -> v2
```

## Headers

Direct proxy tests expose the v4 decision in response headers:

```text
x-router-mode: v4
x-router-selected-version: v1 | v2 | v3
x-router-route-reason: why v4 chose that version
x-router-policy: model policy used by the chosen route
```

For v3 ensemble choices, the proxy also returns:

```text
x-router-advisor-models: model-a,model-b,model-c
```

## Command

```bash
claude-routerv4
```

Equivalent explicit command:

```bash
claude-router --mode v4
```

Default local proxy:

```text
http://127.0.0.1:8792
```

## Direct Tests

Simple v1-style request:

```bash
curl -s -D /tmp/routerv4-simple.headers http://127.0.0.1:8792/v1/messages \
  -H 'content-type: application/json' \
  -d '{"model":"qwen/qwen3-coder:free","max_tokens":80,"messages":[{"role":"user","content":"Say hello in five words."}]}' \
  > /tmp/routerv4-simple.json
rg -i 'x-router' /tmp/routerv4-simple.headers
```

Ensemble v3-style request:

```bash
curl -s -D /tmp/routerv4-ensemble.headers http://127.0.0.1:8792/v1/messages \
  -H 'content-type: application/json' \
  -d '{"model":"qwen/qwen3-coder:free","max_tokens":160,"messages":[{"role":"user","content":"Compare the tradeoffs of v1, v2, and v3 for a routing gateway."}]}' \
  > /tmp/routerv4-ensemble.json
rg -i 'x-router' /tmp/routerv4-ensemble.headers
```

Claude command:

```bash
claude-routerv4 -p 'Say ROUTER_V4_OK and nothing else.' --output-format text
```

Note: Claude Code often sends tool schemas even for simple `-p` requests. In that case v4 intentionally chooses v2.
