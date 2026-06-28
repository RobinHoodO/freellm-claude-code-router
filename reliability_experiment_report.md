# FreeLLM Claude Router: Reliability Experiment Report
Generated on: 2026-06-28 11:14:07 Local Time

This benchmark compares the reliability, latency, and recovery capabilities of the four router variants (v1, v2, v3, v4) using your self-hosted FreeLLMAPI instance.

## Executive Summary

| Variant | Total Requests | Successes | Success Rate | Avg Latency (s) | Fallbacks Triggered |
| --- | --- | --- | --- | --- | --- |
| v1 (Single Model) | 10 | 10 | 100.0% | 8.26s | 10 |
| v2 (Task-Aware) | 10 | 10 | 100.0% | 4.83s | 6 |
| v3 (Ensemble) | 10 | 10 | 100.0% | 2.93s | 2 |
| v4 (Meta-Router) | 10 | 10 | 100.0% | 6.52s | 8 |

## Reliability Evaluation

> **Verdict**: **v3 (Ensemble)** proved to be the most reliable option during this benchmark run, achieving a **100.0%** success rate.

### Key Insights:
- **Version 1 (Baseline)** is fast but vulnerable to transient API provider rate limits (429s) or model failures because it makes a single static request.
- **Version 2 (Task-Aware)** improves reliability significantly by retrying alternate compatible models in the policy pool when the first model fails.
- **Version 3 (Ensemble)** has higher latency due to parallel advisor calls and synthesis steps. If advisors fail, it falls back to single-model execution.
- **Version 4 (Meta-Router)** routes dynamically. It balances speed for simple tasks (v1), robustness for coding/tools (v2), and multi-perspective synthesis for strategy (v3).

## Detailed Scenario Runs

### v1 (Single Model)
| Scenario | Status | Latency | Policy / Selected Model | Fallback? | Notes |
| --- | --- | --- | --- | --- | --- |
| Simple Chat | ✅ (200) | 7.03s | `v1` → `llama-3.3-70b-versatile` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Coding Task | ✅ (200) | 7.09s | `v1` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Comparison/Synthesis | ✅ (200) | 6.99s | `v1` → `llama-3.3-70b-versatile` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Tool Use | ✅ (200) | 7.21s | `v1` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Large Context | ✅ (200) | 14.06s | `v1` → `openai/gpt-oss-20b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}'; gemini-2.5-flash (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Simple Chat | ✅ (200) | 6.67s | `v1` → `llama-3.3-70b-versatile` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Coding Task | ✅ (200) | 6.91s | `v1` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Comparison/Synthesis | ✅ (200) | 6.88s | `v1` → `llama-3.3-70b-versatile` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Tool Use | ✅ (200) | 6.68s | `v1` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Large Context | ✅ (200) | 13.07s | `v1` → `openai/gpt-oss-20b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}'; gemini-2.5-flash (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |

### v2 (Task-Aware)
| Scenario | Status | Latency | Policy / Selected Model | Fallback? | Notes |
| --- | --- | --- | --- | --- | --- |
| Simple Chat | ✅ (200) | 0.19s | `fast` → `llama-3.3-70b-versatile` | No |  |
| Coding Task | ✅ (200) | 7.57s | `coding` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Comparison/Synthesis | ✅ (200) | 0.62s | `fast` → `llama-3.3-70b-versatile` | No |  |
| Tool Use | ✅ (200) | 7.07s | `coding` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Large Context | ✅ (200) | 7.01s | `summarization` → `openai/gpt-oss-20b:free` | ⚠️ Yes | gemini-2.5-flash (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Simple Chat | ✅ (200) | 0.18s | `fast` → `llama-3.3-70b-versatile` | No |  |
| Coding Task | ✅ (200) | 7.18s | `coding` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Comparison/Synthesis | ✅ (200) | 0.60s | `fast` → `llama-3.3-70b-versatile` | No |  |
| Tool Use | ✅ (200) | 6.68s | `coding` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Large Context | ✅ (200) | 11.15s | `summarization` → `openai/gpt-oss-20b:free` | ⚠️ Yes | gemini-2.5-flash (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |

### v3 (Ensemble)
| Scenario | Status | Latency | Policy / Selected Model | Fallback? | Notes |
| --- | --- | --- | --- | --- | --- |
| Simple Chat | ✅ (200) | 1.00s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Coding Task | ✅ (200) | 1.76s | `ensemble:coding` → `openai/gpt-oss-120b:free` | No |  |
| Comparison/Synthesis | ✅ (200) | 1.89s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Tool Use | ✅ (200) | 6.97s | `coding` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Large Context | ✅ (200) | 3.20s | `ensemble:summarization` → `openai/gpt-oss-120b:free` | No |  |
| Simple Chat | ✅ (200) | 1.08s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Coding Task | ✅ (200) | 1.91s | `ensemble:coding` → `openai/gpt-oss-120b:free` | No |  |
| Comparison/Synthesis | ✅ (200) | 1.76s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Tool Use | ✅ (200) | 7.85s | `coding` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models rate-limited. Last error: OpenRouter API error 429: Provider returned error","type":"rate_limit_error"}}' |
| Large Context | ✅ (200) | 1.88s | `ensemble:summarization` → `openai/gpt-oss-120b:free` | No |  |

### v4 (Meta-Router)
| Scenario | Status | Latency | Policy / Selected Model | Fallback? | Notes |
| --- | --- | --- | --- | --- | --- |
| Simple Chat | ✅ (200) | 6.52s | `v1` → `llama-3.3-70b-versatile` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Coding Task | ✅ (200) | 6.93s | `coding` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Comparison/Synthesis | ✅ (200) | 8.27s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Tool Use | ✅ (200) | 6.70s | `coding` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Large Context | ✅ (200) | 6.70s | `summarization` → `openai/gpt-oss-20b:free` | ⚠️ Yes | gemini-2.5-flash (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Simple Chat | ✅ (200) | 6.69s | `v1` → `llama-3.3-70b-versatile` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Coding Task | ✅ (200) | 6.99s | `coding` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Comparison/Synthesis | ✅ (200) | 2.21s | `ensemble:fast` → `openai/gpt-oss-120b:free` | No |  |
| Tool Use | ✅ (200) | 6.96s | `coding` → `openai/gpt-oss-120b:free` | ⚠️ Yes | qwen/qwen3-coder:free (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |
| Large Context | ✅ (200) | 7.25s | `summarization` → `openai/gpt-oss-20b:free` | ⚠️ Yes | gemini-2.5-flash (attempt 3): POST http://127.0.0.1:3004/v1/chat/completions failed with HTTP 429: b'{"error":{"message":"All models exhausted. Add more API keys or wait for rate limits to reset.","type":"routing_error"}}' |

