# FreeLLM Claude Router: Reliability Experiment Report
Generated on: 2026-06-28 09:43:45 Local Time

This benchmark compares the reliability, latency, and recovery capabilities of the four router variants (v1, v2, v3, v4) using your self-hosted FreeLLMAPI instance.

## Executive Summary

| Variant | Total Requests | Successes | Success Rate | Avg Latency (s) | Fallbacks Triggered |
| --- | --- | --- | --- | --- | --- |
| v1 (Single Model) | 10 | 10 | 100.0% | 1.92s | 0 |
| v2 (Task-Aware) | 10 | 10 | 100.0% | 1.65s | 2 |
| v3 (Ensemble) | 10 | 10 | 100.0% | 4.43s | 0 |
| v4 (Meta-Router) | 10 | 10 | 100.0% | 2.46s | 2 |

## Reliability Evaluation

> **Verdict**: **v2 (Task-Aware)** proved to be the most reliable option during this benchmark run, achieving a **100.0%** success rate.

### Key Insights:
- **Version 1 (Baseline)** is fast but vulnerable to transient API provider rate limits (429s) or model failures because it makes a single static request.
- **Version 2 (Task-Aware)** improves reliability significantly by retrying alternate compatible models in the policy pool when the first model fails.
- **Version 3 (Ensemble)** has higher latency due to parallel advisor calls and synthesis steps. If advisors fail, it falls back to single-model execution.
- **Version 4 (Meta-Router)** routes dynamically. It balances speed for simple tasks (v1), robustness for coding/tools (v2), and multi-perspective synthesis for strategy (v3).

## Detailed Scenario Runs

### v1 (Single Model)
| Scenario | Status | Latency | Policy / Selected Model | Fallback? | Notes |
| --- | --- | --- | --- | --- | --- |
| Simple Chat | ✅ (200) | 1.59s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Coding Task | ✅ (200) | 2.24s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Comparison/Synthesis | ✅ (200) | 2.42s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Tool Use | ✅ (200) | 1.62s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Large Context | ✅ (200) | 2.17s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Simple Chat | ✅ (200) | 1.56s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Coding Task | ✅ (200) | 2.04s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Comparison/Synthesis | ✅ (200) | 2.29s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Tool Use | ✅ (200) | 1.58s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Large Context | ✅ (200) | 1.69s | `v1` → `qwen/qwen3-coder:free` | No |  |

### v2 (Task-Aware)
| Scenario | Status | Latency | Policy / Selected Model | Fallback? | Notes |
| --- | --- | --- | --- | --- | --- |
| Simple Chat | ✅ (200) | 0.16s | `fast` → `llama-3.3-70b-versatile` | No |  |
| Coding Task | ✅ (200) | 2.10s | `coding` → `qwen/qwen3-coder:free` | No |  |
| Comparison/Synthesis | ✅ (200) | 0.53s | `fast` → `llama-3.3-70b-versatile` | No |  |
| Tool Use | ✅ (200) | 1.58s | `coding` → `qwen/qwen3-coder:free` | No |  |
| Large Context | ✅ (200) | 4.52s | `summarization` → `openai/gpt-oss-20b:free` | ⚠️ Yes | gemini-2.5-flash: POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Simple Chat | ✅ (200) | 0.21s | `fast` → `llama-3.3-70b-versatile` | No |  |
| Coding Task | ✅ (200) | 2.92s | `coding` → `qwen/qwen3-coder:free` | No |  |
| Comparison/Synthesis | ✅ (200) | 0.71s | `fast` → `llama-3.3-70b-versatile` | No |  |
| Tool Use | ✅ (200) | 1.74s | `coding` → `qwen/qwen3-coder:free` | No |  |
| Large Context | ✅ (200) | 2.04s | `summarization` → `openai/gpt-oss-20b:free` | ⚠️ Yes | gemini-2.5-flash: POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |

### v3 (Ensemble)
| Scenario | Status | Latency | Policy / Selected Model | Fallback? | Notes |
| --- | --- | --- | --- | --- | --- |
| Simple Chat | ✅ (200) | 2.91s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Coding Task | ✅ (200) | 4.62s | `ensemble:coding` → `openai/gpt-oss-120b:free` | No |  |
| Comparison/Synthesis | ✅ (200) | 4.98s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Tool Use | ✅ (200) | 1.54s | `coding` → `qwen/qwen3-coder:free` | No |  |
| Large Context | ✅ (200) | 6.98s | `ensemble:summarization` → `openai/gpt-oss-120b:free` | No |  |
| Simple Chat | ✅ (200) | 6.23s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Coding Task | ✅ (200) | 3.69s | `ensemble:coding` → `openai/gpt-oss-120b:free` | No |  |
| Comparison/Synthesis | ✅ (200) | 5.85s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Tool Use | ✅ (200) | 1.97s | `coding` → `qwen/qwen3-coder:free` | No |  |
| Large Context | ✅ (200) | 5.53s | `ensemble:summarization` → `openai/gpt-oss-120b:free` | No |  |

### v4 (Meta-Router)
| Scenario | Status | Latency | Policy / Selected Model | Fallback? | Notes |
| --- | --- | --- | --- | --- | --- |
| Simple Chat | ✅ (200) | 1.46s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Coding Task | ✅ (200) | 2.09s | `coding` → `qwen/qwen3-coder:free` | No |  |
| Comparison/Synthesis | ✅ (200) | 2.14s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Tool Use | ✅ (200) | 1.49s | `coding` → `qwen/qwen3-coder:free` | No |  |
| Large Context | ✅ (200) | 2.36s | `summarization` → `openai/gpt-oss-20b:free` | ⚠️ Yes | gemini-2.5-flash: POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Simple Chat | ✅ (200) | 1.64s | `v1` → `qwen/qwen3-coder:free` | No |  |
| Coding Task | ✅ (200) | 2.34s | `coding` → `qwen/qwen3-coder:free` | No |  |
| Comparison/Synthesis | ✅ (200) | 5.03s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Tool Use | ✅ (200) | 1.60s | `coding` → `qwen/qwen3-coder:free` | No |  |
| Large Context | ✅ (200) | 4.44s | `summarization` → `openai/gpt-oss-20b:free` | ⚠️ Yes | gemini-2.5-flash: POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |

