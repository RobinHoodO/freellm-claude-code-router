# FreeLLMAPI Model Routing Map

This map organizes all the available models exposed by your self-hosted **FreeLLMAPI** instance by task category, highlighting their context windows and potential routing fits.

---

## 1. Coding & Software Development
*Best for code generation, debugging, refactoring, test suite creation, and tool-use scripts.*

| Model ID | Model Name | Context Window | Best Use Case |
| :--- | :--- | :--- | :--- |
| `qwen3-coder-480b` | Qwen3 Coder 480B | 1,048,576 tokens | Premium coding model with massive multi-file context capability. |
| `qwen3-coder-next` | Qwen3 Coder Next | 262,144 tokens | Large context general coder. |
| `codestral` | Codestral | 256,000 tokens | Specialized, fast code generation model. |
| `poolside-laguna-m.1` | Poolside Laguna M.1 | 262,144 tokens | Specialized software engineering agent model. |
| `poolside-laguna-xs.2` | Poolside Laguna XS.2 | 131,072 tokens | Lightweight software engineering model. |
| `deepseek-r1-distill-qwen-32b`| DeepSeek R1 Distill Qwen 32B | 131,072 tokens | Reason-before-acting distill model, great for logic bugs. |

---

## 2. Reasoning, Strategy & Synthesis (Ensemble Advisors)
*Best for structural choices, design patterns, tradeoff comparisons, and v3 ensemble critiques.*

| Model ID | Model Name | Context Window | Best Use Case |
| :--- | :--- | :--- | :--- |
| `deepseek-v4-pro` | DeepSeek V4 Pro | 131,072 tokens | High-reasoning reasoning model. |
| `mistral-large-3-675b` | Mistral Large 3 675B | 131,072 tokens | Robust agent for general complex reasoning and aggregations. |
| `hermes-3-405b` | Hermes 3 405B | 131,072 tokens | Full-size open weights model for complex logic and instructions. |
| `nemotron-3-nano-30b-reasoning`| Nemotron 3 Nano 30B Reasoning | 262,144 tokens | Specialized reasoning advisor. |
| `command-a-reasoning` | Command A Reasoning | 256,000 tokens | Logic-first search-capable agent. |
| `liquid-lfm-2.5-1.2b-thinking`| Liquid LFM 2.5 1.2B Thinking | 32,768 tokens | Lightweight thinking advisor. |

---

## 3. Long Context Processing & Summarization
*Best for reading large logs, auditing codebases, summarizing documents, and code reviews.*

| Model ID | Model Name | Context Window | Best Use Case |
| :--- | :--- | :--- | :--- |
| `nemotron-3-super-120b` | Nemotron 3 Super 120B | 1,000,000 tokens | Extreme long context processing (e.g., massive file analysis). |
| `kimi-k2.6` | Kimi K2.6 | 262,144 tokens | Highly competent long-context assistant. |
| `command-r-2` | Command R+ | 131,072 tokens | Premium search and long context RAG engine. |
| `command-r` | Command R | 131,072 tokens | Standard search and long context engine. |
| `nemotron-3-120b` | Nemotron 3 120B | 262,144 tokens | General document processing. |

---

## 4. Fast, Lightweight & Simple Tasks (Baselines)
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

---

## 5. Vision & Multimodal Tasks
*Best for UI screenshot analysis, layouts audits, and diagram reading.*

| Model ID | Model Name | Context Window | Best Use Case |
| :--- | :--- | :--- | :--- |
| `glm-4.6v-flash` | GLM-4.6V Flash | 131,072 tokens | Fast multimodal inputs (images, diagrams). |
| `nemotron-nano-12b-vl` | Nemotron Nano 12B VL | 128,000 tokens | Vision-language understanding tasks. |
