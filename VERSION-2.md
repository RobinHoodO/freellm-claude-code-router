# Version 2: Task-Aware Single-Model Router

Status: working.

Version 2 should still send each Claude request to one model, but the model should be chosen from a task-specific policy.

## Planned Shape

```text
Claude Code request
  -> local proxy
    -> classify task
      -> choose policy
        -> choose one compatible FreeLLMAPI model
          -> FreeLLMAPI fallback underneath
```

If the first selected model returns a provider/rate-limit error, the proxy now retries other compatible allowlisted models before failing the request.

## Example Policies

```text
coding
  qwen/qwen3-coder:free
  openai/gpt-oss-120b:free
  llama-3.3-70b-versatile

fast
  openai/gpt-oss-20b:free
  llama-3.3-70b-versatile

long-context
  qwen/qwen3-coder:free
  gemini-2.5-flash

review
  openai/gpt-oss-120b:free
  z-ai/glm-4.5-air:free
```

## Command

```bash
claude-routerv2
```

Equivalent:

```bash
claude-router --mode v2
```

## Test

```bash
claude-routerv2 -p 'Summarize the router system in one sentence.' --output-format text
```

## Port

Version 2 uses its own local proxy port:

```text
http://127.0.0.1:8791
```

This was moved to `8791` because another local process was already using `8788`.
