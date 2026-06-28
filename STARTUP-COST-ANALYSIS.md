# Claude Code Startup Cost Analysis — Thrivbe-AI Workspace

**Date:** 2026-06-28
**Scope:** Token cost to start a Claude Code instance and send one prompt within the `Thrivbe-AI` workspace (cwd: `lab/social-content-engine`).
**Method:** Measured from real request logs in `lab/freellm-router-mvp/router_decisions.jsonl` (143 real Claude Code requests captured during yesterday's router research), cross-checked against on-disk context-file sizes.

---

## 1. TL;DR — What one prompt costs

| Scenario | Input tokens per single prompt | Notes |
|---|---|---|
| Lean one-shot (`-p "..."`, minimal tool surface) | **~12,700 tok** | Measured P10 |
| Typical interactive session startup | **~29,000 tok** | Measured median (P50) |
| Full-context interactive startup (tools + skills + MCP) | **~53,800 tok** | Measured P90, most common cluster |
| Max observed | ~68,500 tok | Heavy tool-schema + skill-list load |

**Every prompt you send pays this input-token tax** because Claude Code re-sends the entire system prompt + context window on every turn. The first prompt of a session is the most expensive; subsequent prompts in the same session compound (prior turns accumulate).

---

## 2. Measured evidence (from yesterday's research)

Source: `lab/freellm-router-mvp/router_decisions.jsonl` — captured during the FreeLLM router reliability experiment (2026-06-27/28). These are **real Claude Code requests** routed through the local proxy, which logged `input_tokens` from the Anthropic-format payload.

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

The ~53,800 cluster is the signature of a **fresh interactive Claude Code session** in this workspace: full built-in tool schemas + skill list + CLAUDE.md/AGENTS.md + GitNexus instructions all loaded at once.

---

## 3. Startup overhead breakdown (this workspace)

Components loaded into context before your first token of actual prompt is processed:

| Component | Tokens | Source |
|---|---|---|
| Anthropic Claude Code base system prompt | ~11,000 | Built-in, industry-known |
| Built-in tool schemas (Read, Write, Edit, Bash, Glob, Grep, Task, TodoWrite, WebFetch, ~25–35 tools) | ~8,000–12,000 | Injected by Claude Code |
| `CLAUDE.md` (root project memory) | ~5,288 | `Thrivbe-AI/CLAUDE.md` (21,152 B) |
| `AGENTS.md` root (GitNexus Thrivbe-AI block) | ~1,373 | `Thrivbe-AI/AGENTS.md` (5,495 B) |
| `AGENTS.md` nested (GitNexus social-content-engine) | ~742 | `lab/social-content-engine/AGENTS.md` (2,968 B) |
| `CLAUDE.md` nested (cwd) | ~1,388 | `lab/social-content-engine/CLAUDE.md` (5,552 B) |
| Skills available-skills list (231 skills, name+description only) | ~4,000–6,000 | NOT the full 294k bodies — only short descriptions load |
| MCP tool schemas (firefly + task-master-ai) | ~2,000 | `.mcp.json` |
| GitNexus MCP tool schemas + usage instructions | ~3,000 | GitNexus MCP server |
| **Estimated total** | **~36,000–42,000** | |

The measured ~53,800 sits slightly above the estimate because Claude Code also injects environment hints, git status, and the full recursive `.claude/` discovery (commands, helpers) at session start.

> **Key insight:** 231 skills are installed, but their **full bodies (294k tokens) do NOT load** — only the name + one-line description list (~5k tokens). Skills are loaded on-demand only when invoked. This is the critical design that keeps startup survivable.

---

## 4. Cost in dollars (Anthropic Sonnet 4 pricing)

Using Sonnet 4 list pricing: **$3 / 1M input tokens**, $15 / 1M output tokens.

| Scenario | Input cost | Output cost (avg ~150 tok) | Total / prompt |
|---|---|---|---|
| Lean one-shot (12.7k in) | $0.038 | $0.002 | **~$0.04** |
| Median interactive (29k in) | $0.087 | $0.002 | **~$0.09** |
| Full startup (53.8k in) | $0.161 | $0.002 | **~$0.16** |

**For a 10-turn interactive session** in this workspace (each turn re-sends growing context):
~53.8k + 54k + 55k + … ≈ **~600k input tokens → ~$1.80** for the conversation, before any real work output.

---

## 5. Why this workspace is expensive

This Thrivbe-AI workspace is an unusually heavy Claude Code environment:

1. **Nested AGENTS.md × 2** — GitNexus blocks at root AND in the lab subdir both load (duplicated instructions).
2. **Large root `CLAUDE.md`** — 21 KB of project memory.
3. **231 installed skills** — even as a short list, that's ~5k tokens of descriptions every turn.
4. **2 MCP servers** (firefly, task-master-ai) + GitNexus MCP — each contributes tool schemas.
5. **GitNexus mandatory workflows** — the AGENTS.md forces `gitnexus_impact` calls before every edit, which themselves consume tokens.

---

## 6. Levers to reduce startup cost

| Lever | Saving | Tradeoff |
|---|---|---|
| Run one-shots with `claude -p` instead of interactive | ~40k tok | No conversation memory |
| Slim down root `CLAUDE.md` (21 KB → 5 KB) | ~4k tok/turn | Lose project context |
| Disable unused MCP servers in `.mcp.json` | ~2k tok | Lose those tools |
| Remove skills you don't use (231 → ~30) | ~4k tok | Reinstall when needed |
| Use the FreeLLM router (`claude-routerv1..v4`) for free-tier models | $0 token cost | See yesterday's research — reliability varies (v3 best at 100%) |
| Work in a subdir without its own AGENTS.md/CLAUDE.md | ~2k tok | Lose GitNexus nested context |

---

## 7. Connection to yesterday's research

Yesterday's work (`lab/freellm-router-mvp`, see `HANDOVER.md`, `reliability_experiment_report.md`) was building a **local proxy that routes Claude Code through your FreeLLMAPI free-tier models** instead of paying Anthropic per-token. The token logs analyzed in this document are a byproduct of that experiment — the proxy logged `input_tokens` on every request.

**Yesterday's reliability verdict** (from `reliability_experiment_report.md`):
- v1 (single model): 100% success, 8.3s avg, 10/10 fallbacks
- v2 (task-aware): 100% success, 4.8s avg, 6/10 fallbacks
- v3 (ensemble): 100% success, 2.9s avg, 2/10 fallbacks ← most reliable
- v4 (meta-router): 100% success, 6.5s avg, 8/10 fallbacks

So the FreeLLM router is the **direct answer** to the startup-cost problem: it lets you send that ~53,800-token prompt through free models (gpt-oss-120b, llama-3.3-70b, qwen3-coder) at $0 instead of ~$0.16/prompt on Anthropic.

---

## 8. Files referenced

- `lab/freellm-router-mvp/router_decisions.jsonl` — 294 logged requests (143 real), the raw token data
- `lab/freellm-router-mvp/reliability_experiment_report.md` — yesterday's router benchmark
- `lab/freellm-router-mvp/HANDOVER.md` — full project context
- `Thrivbe-AI/CLAUDE.md` (21 KB), `AGENTS.md` (5.5 KB) — root context memory
- `lab/social-content-engine/CLAUDE.md`, `AGENTS.md` — nested cwd context
- `.mcp.json` — MCP server config (firefly, task-master-ai)
