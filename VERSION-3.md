# Version 3: Multi-Model Ensemble Router

Status: working for text-only requests. Tool-bearing Claude Code requests safely fall back to the v2 single-model path.

If an advisor model fails or rate-limits, v3 skips that advisor and continues with the advisors that answered. If no advisor answers, it falls back to one compatible single model.

Version 3 should be an orchestrator, not just a router.

## Planned Shape

```text
Claude Code request
  -> local proxy
    -> classify task
      -> ask multiple advisor models
      -> aggregate / critique / synthesize
      -> return one final answer to Claude Code
```

## Safety Rule For Claude Code

Only one model should be allowed to drive tool calls.

```text
primary model
  may use tools / act

advisor models
  text-only suggestions, critiques, alternatives

aggregator
  merges into one final response
```

## Good Fit

```text
planning
architecture
debugging hypotheses
code review
large-context summarization
implementation strategy
```

## Bad Fit

```text
every shell/tool call
small edits
fast interactive loops
streaming token-by-token UX
```

## Command

```bash
claude-routerv3
```

Equivalent:

```bash
claude-router --mode v3
```

## Port

Version 3 uses its own local proxy port:

```text
http://127.0.0.1:8789
```

## Test

Direct ensemble test:

```bash
curl -s http://127.0.0.1:8789/v1/messages \
  -H 'content-type: application/json' \
  -d '{"model":"qwen/qwen3-coder:free","max_tokens":160,"messages":[{"role":"user","content":"Explain the router system in one sentence."}]}' | python3 -m json.tool
```

Claude Code test:

```bash
claude-routerv3 -p 'Say ROUTER_V3_OK and nothing else.' --output-format text
```

Note: Claude Code often sends tool schemas even for `-p` requests. In that case v3 uses the safe v2 single-model path instead of ensemble.
