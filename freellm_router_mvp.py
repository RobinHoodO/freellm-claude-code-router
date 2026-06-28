#!/usr/bin/env python3
"""
FreeLLM Claude Code router MVP.

This single-file prototype proves the core thesis:
1. Discover/test candidate FreeLLM models.
2. Build a compatibility allowlist.
3. Put an Anthropic-compatible /v1/messages proxy in front of the model API.
4. Route only to models that support the request shape.

It can run fully offline with a mock OpenAI-compatible FreeLLM API:
  python3 freellm_router_mvp.py demo

Or against a real OpenAI-compatible endpoint:
  FREE_LLM_API_BASE=http://thrivbe-host:PORT python3 freellm_router_mvp.py probe
  FREE_LLM_API_BASE=http://thrivbe-host:PORT python3 freellm_router_mvp.py proxy
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import http.client
import concurrent.futures
import json
import os
import re
import signal
import sys
import traceback
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


DEFAULT_ALLOWLIST_PATH = "models.allowlist.json"
DEFAULT_MOCK_BASE = "http://127.0.0.1:8091"
DEFAULT_PROXY_BASE = "http://127.0.0.1:8787"

# Thread-safe JSONL decision logger
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DECISION_LOG_PATH = os.path.join(SCRIPT_DIR, "router_decisions.jsonl")
log_lock = threading.Lock()

def log_decision(entry: dict[str, Any]) -> None:
    entry.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with log_lock:
        try:
            with open(DECISION_LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except Exception as exc:
            if os.environ.get("MVP_VERBOSE"):
                print(f"Failed to write decision log: {exc}", file=sys.stderr)

V2_POLICIES = {
    "long-context": [
        "nemotron-3-super-120b",
        "mistral-large-3-675b",
        "kimi-k2.6",
        "gpt-4.1",
        "gpt-oss-120b",
        "llama-3.3-70b",
    ],
    "coding": [
        "mistral-large-3-675b",
        "gpt-oss-120b",
        "gpt-4.1",
        "llama-3.3-70b",
        "gpt-oss-20b",
    ],
    "review": [
        "mistral-large-3-675b",
        "kimi-k2.6",
        "command-a-reasoning",
        "gpt-4.1",
        "llama-3.3-70b",
        "gpt-oss-120b",
    ],
    "summarization": [
        "mistral-large-3-675b",
        "nemotron-3-super-120b",
        "kimi-k2.6",
        "gpt-oss-120b",
        "gpt-oss-20b",
        "llama-3.3-70b",
    ],
    "reasoning": [
        "command-a-reasoning",
        "mistral-large-3-675b",
        "kimi-k2.6",
        "nemotron-3-super-120b",
    ],
    "fast": [
        "llama-3.3-70b",
        "gpt-oss-20b",
    ],
}


@dataclasses.dataclass
class ModelCapability:
    model: str
    claude_code_compatible: bool
    supports_tools: bool
    supports_streaming: bool
    context_window: int
    roles: list[str]
    notes: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "claudeCodeCompatible": self.claude_code_compatible,
            "supportsTools": self.supports_tools,
            "supportsStreaming": self.supports_streaming,
            "contextWindow": self.context_window,
            "roles": self.roles,
            "notes": self.notes,
        }


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length") or 0)
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def write_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
    encoded = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(encoded)))
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(encoded)


def write_sse(handler: BaseHTTPRequestHandler, event: str, payload: dict[str, Any]) -> None:
    handler.wfile.write(f"event: {event}\n".encode("utf-8"))
    handler.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
    handler.wfile.flush()


def write_anthropic_stream(handler: BaseHTTPRequestHandler, response: dict[str, Any]) -> None:
    handler.send_response(200)
    handler.send_header("content-type", "text/event-stream")
    handler.send_header("cache-control", "no-cache")
    handler.send_header("connection", "close")
    handler.end_headers()
    handler.close_connection = True

    message = {key: value for key, value in response.items() if key != "content"}
    message["content"] = []
    write_sse(handler, "message_start", {"type": "message_start", "message": message})

    for index, block in enumerate(response.get("content", [])):
        if block.get("type") == "tool_use":
            start_block = {
                "type": "tool_use",
                "id": block.get("id", f"toolu_mvp_{index}"),
                "name": block.get("name", "tool"),
                "input": {},
            }
            write_sse(handler, "content_block_start", {"type": "content_block_start", "index": index, "content_block": start_block})
            write_sse(
                handler,
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "input_json_delta", "partial_json": json.dumps(block.get("input", {}))},
                },
            )
        else:
            start_block = {"type": "text", "text": ""}
            write_sse(handler, "content_block_start", {"type": "content_block_start", "index": index, "content_block": start_block})
            text = str(block.get("text", ""))
            if text:
                write_sse(
                    handler,
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": text},
                    },
                )
        write_sse(handler, "content_block_stop", {"type": "content_block_stop", "index": index})

    write_sse(
        handler,
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": response.get("stop_reason", "end_turn"), "stop_sequence": response.get("stop_sequence")},
            "usage": {"output_tokens": response.get("usage", {}).get("output_tokens", 0)},
        },
    )
    write_sse(handler, "message_stop", {"type": "message_stop"})


def http_json(method: str, url: str, payload: dict[str, Any] | None = None, auth_token: str | None = None, timeout: float = 30) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    headers = {"content-type": "application/json"}
    if auth_token:
        headers["authorization"] = f"Bearer {auth_token}"

    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = connection_cls(parsed.netloc, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read()
        if response.status >= 400:
            raise RuntimeError(f"{method} {url} failed with HTTP {response.status}: {data[:500]!r}")
        if not data:
            return {}
        return json.loads(data.decode("utf-8"))
    finally:
        conn.close()


def join_v1_url(api_base: str, endpoint: str) -> str:
    base = api_base.rstrip("/")
    endpoint = endpoint.lstrip("/")
    if base.endswith("/v1"):
        return f"{base}/{endpoint.removeprefix('v1/')}"
    return f"{base}/{endpoint}"


def extract_text_from_anthropic_messages(messages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    chunks.append(str(block.get("text", "")))
    return "\n".join(chunks)


def sanitize_tool_parameters(schema: Any) -> Any:
    if isinstance(schema, dict):
        new_schema = {}
        for k, v in schema.items():
            if k == "enum" and isinstance(v, list) and len(v) > 10:
                # Strip massive enum lists (like files list) to prevent token bloat
                continue
            new_schema[k] = sanitize_tool_parameters(v)
        return new_schema
    elif isinstance(schema, list):
        return [sanitize_tool_parameters(item) for item in schema]
    return schema


def prune_unused_tools(tools: list[dict[str, Any]], request_text: str) -> list[dict[str, Any]]:
    # Core tools that should NEVER be pruned
    core_prefixes = {"Bash", "Edit", "Read", "SendMessage", "Skill", "Cron", "StructuredOutput", "Notebook", "ExitWorktree", "EnterWorktree", "Task"}
    
    pruned_tools = []
    text_lower = request_text.lower()
    
    for tool in tools:
        name = tool.get("name", "")
        # If it's a core tool, keep it
        if any(name.startswith(p) for p in core_prefixes):
            pruned_tools.append(tool)
            continue
            
        # Specific check for third-party MCP integration tools to prevent payload bloat
        if name.startswith("mcp__"):
            parts = name.split("__")
            if len(parts) >= 2:
                provider = parts[1]
                if provider not in {"obsidian", "gitnexus", "context7"}:
                    kw_map = {
                        "cal": ["cal.com", "calendar", "booking"],
                        "stripe": ["stripe", "payment", "refund"],
                        "supabase": ["supabase"],
                        "apify": ["apify"],
                        "beeper": ["beeper"],
                        "blotato": ["blotato", "pinterest"],
                        "twenty": ["twenty", "crm"]
                    }
                    kws = kw_map.get(provider, [provider])
                    if not any(kw in text_lower for kw in kws):
                        # Prune it since it is not requested in the prompt
                        continue
            
        # General size filter for non-core tools: if serialized size is > 15,000 characters
        # and none of its name parts are in the prompt, we prune it.
        tool_len = len(json.dumps(tool))
        if tool_len > 15000:
            keywords = [part for part in name.lower().split("__") if part]
            if any(kw in text_lower for kw in keywords):
                pruned_tools.append(tool)
            else:
                print(f"[DEBUG] Pruned massive tool {name} (size: {tool_len} chars)", file=sys.stderr)
            continue
            
        pruned_tools.append(tool)
        
    return pruned_tools


def truncate_text(text: str, max_len: int = 150) -> str:
    if not isinstance(text, str):
        return text
    text = text.strip()
    if not text:
        return text
    parts = text.split("\n")
    first_line = parts[0].strip()
    if len(first_line) > max_len:
        return first_line[:max_len] + "..."
    return first_line


def clean_and_truncate_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        new_schema = {}
        for k, v in schema.items():
            if k == "description" and isinstance(v, str):
                new_schema[k] = truncate_text(v)
            else:
                new_schema[k] = clean_and_truncate_schema(v)
        return new_schema
    elif isinstance(schema, list):
        return [clean_and_truncate_schema(item) for item in schema]
    return schema


def anthropic_to_openai_payload(request: dict[str, Any], model: str) -> dict[str, Any]:
    openai_messages: list[dict[str, str]] = []
    system = request.get("system")
    if isinstance(system, str) and system:
        openai_messages.append({"role": "system", "content": system})
    for message in request.get("messages", []):
        role = message.get("role", "user")
        if role not in {"user", "assistant", "system"}:
            role = "user"
        openai_messages.append({"role": role, "content": extract_text_from_anthropic_messages([message])})

    payload: dict[str, Any] = {
        "model": model,
        "messages": openai_messages,
        "temperature": request.get("temperature", 0.2),
        "max_tokens": min(request.get("max_tokens", 4096), 4096) if request.get("max_tokens") is not None else 4096,
        "stream": False,
    }
    tools = request.get("tools")
    if tools:
        user_texts = []
        for msg in request.get("messages", []):
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    if "system-reminder" not in content.lower()[:50]:
                        user_texts.append(content)
                elif isinstance(content, list):
                    for chunk in content:
                        if isinstance(chunk, dict) and chunk.get("type") == "text":
                            text_val = chunk.get("text", "")
                            if "system-reminder" not in text_val.lower()[:50]:
                                user_texts.append(text_val)
        request_text = " ".join(user_texts)
        print(f"[DEBUG] prune_unused_tools: request_text length={len(request_text)} content={repr(request_text[:200])}", file=sys.stderr)
        pruned_tools_list = prune_unused_tools(tools, request_text)

        payload["tools"] = []
        for tool in pruned_tools_list:
            mapped_tool = {
                "type": "function",
                "function": {
                    "name": tool.get("name", "tool"),
                    "description": truncate_text(tool.get("description", "")),
                    "parameters": clean_and_truncate_schema(sanitize_tool_parameters(tool.get("input_schema", {"type": "object", "properties": {}}))),
                },
            }
            print(f"[DEBUG] Tool: {tool.get('name')}, original: {len(json.dumps(tool))} chars, truncated: {len(json.dumps(mapped_tool))} chars", file=sys.stderr)
            payload["tools"].append(mapped_tool)
            
        with open("/tmp/last_tools_payload.json", "w") as f:
            json.dump(payload["tools"], f, indent=2)
        tools_str = json.dumps(payload["tools"])
        print(f"[DEBUG] tools_payload_size: {len(tools_str)} chars. First 500: {tools_str[:500]}", file=sys.stderr)
    return payload






def openai_to_anthropic_response(openai_response: dict[str, Any], selected_model: str) -> dict[str, Any]:
    choice = (openai_response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []
    content: list[dict[str, Any]] = []

    for index, tool_call in enumerate(tool_calls):
        function = tool_call.get("function") or {}
        try:
            tool_input = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            tool_input = {"raw_arguments": function.get("arguments") or ""}
        content.append(
            {
                "type": "tool_use",
                "id": tool_call.get("id", f"toolu_mvp_{index}"),
                "name": function.get("name", "tool"),
                "input": tool_input,
            }
        )

    if text or not content:
        content.insert(0, {"type": "text", "text": text})

    return {
        "id": f"msg_mvp_{int(time.time() * 1000)}",
        "type": "message",
        "role": "assistant",
        "model": selected_model,
        "content": content,
        "stop_reason": "tool_use" if tool_calls else "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": openai_response.get("usage", {}).get("prompt_tokens", 0),
            "output_tokens": openai_response.get("usage", {}).get("completion_tokens", 0),
        },
    }


def text_from_openai_response(openai_response: dict[str, Any]) -> str:
    choice = (openai_response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return str(message.get("content") or "")


def estimate_tokens(request: dict[str, Any]) -> int:
    if not isinstance(request, dict):
        return 0
    text = extract_text_from_anthropic_messages(request.get("messages", []))
    system = request.get("system") if isinstance(request.get("system"), str) else ""
    return max(1, (len(text) + len(system)) // 4)



def load_allowlist(path: str) -> list[ModelCapability]:
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return [
        ModelCapability(
            model=item["model"],
            claude_code_compatible=bool(item.get("claudeCodeCompatible")),
            supports_tools=bool(item.get("supportsTools")),
            supports_streaming=bool(item.get("supportsStreaming")),
            context_window=int(item.get("contextWindow", 0)),
            roles=list(item.get("roles", [])),
            notes=str(item.get("notes", "")),
        )
        for item in raw.get("models", [])
    ]


def save_allowlist(path: str, capabilities: list[ModelCapability]) -> None:
    payload = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": [capability.as_json() for capability in capabilities],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def choose_model(request: dict[str, Any], capabilities: list[ModelCapability]) -> ModelCapability:
    needs_tools = bool(request.get("tools") or request.get("tool_choice"))
    tokens = estimate_tokens(request)
    eligible = [
        capability
        for capability in capabilities
        if capability.claude_code_compatible
        and capability.context_window >= tokens
        and (not needs_tools or capability.supports_tools)
    ]
    if not eligible:
        raise RuntimeError(f"No compatible model for request: needs_tools={needs_tools}, estimated_tokens={tokens}")

    text = extract_text_from_anthropic_messages(request.get("messages", [])).lower()
    if needs_tools:
        tool_models = [capability for capability in eligible if "tool_use" in capability.roles]
        if tool_models:
            return tool_models[0]
    if any(word in text for word in ["summarize", "summary", "tl;dr"]):
        summary_models = [capability for capability in eligible if "summarization" in capability.roles]
        if summary_models:
            return summary_models[0]
    if tokens > 8000:
        return max(eligible, key=lambda capability: capability.context_window)
    code_models = [capability for capability in eligible if "coding" in capability.roles]
    return code_models[0] if code_models else eligible[0]


def eligible_models(request: dict[str, Any], capabilities: list[ModelCapability]) -> list[ModelCapability]:
    needs_tools = bool(request.get("tools") or request.get("tool_choice"))
    tokens = estimate_tokens(request)
    return [
        capability
        for capability in capabilities
        if capability.claude_code_compatible
        and capability.context_window >= tokens
        and (not needs_tools or capability.supports_tools)
    ]


def has_any_word(text: str, words: list[str]) -> bool:
    for word in words:
        if " " in word:
            if word in text:
                return True
        else:
            if re.search(r'\b' + re.escape(word) + r'\b', text):
                return True
    return False


def classify_v2_policy(request: dict[str, Any]) -> str:
    tokens = estimate_tokens(request)
    text = extract_text_from_anthropic_messages(request.get("messages", [])).lower()
    has_tools = bool(request.get("tools") or request.get("tool_choice"))
    print(f"[DEBUG] classify_v2_policy: has_tools={has_tools} tokens={tokens} text='{text.strip()[:100]}'", file=sys.stderr)

    if tokens > 60000:
        return "long-context"
    if has_any_word(text, ["reason", "reasoning", "think", "think step", "step by step", "analyze", "analyse", "strategy", "architect", "design pattern", "tradeoff", "trade off", "compare", "pros and cons", "decision", "evaluate", "deduce", "prove", "math", "puzzle", "logic"]):
        return "reasoning"
    if has_any_word(text, ["review", "audit", "critique", "risk", "bug", "regression", "diff", "lint", "vulnerability", "security"]):
        return "review"
    if has_any_word(text, ["summarize", "summary", "tl;dr", "explain", "overview", "explain how", "why does", "what is"]):
        return "summarization"
    if has_tools or has_any_word(text, [
        "code", "implement", "fix", "test", "debug", "refactor", "write a function", "script", "harness", "class", "program",
        "python", "javascript", "typescript", "golang", "rust", "html", "css", "java", "c++", "ruby", "developer", "function",
        "develop", "compile", "syntax", "exception", "error on line", "unittest", "pytest"
    ]):
        return "coding"
    if tokens < 2000:
        return "fast"
    return "coding"


def choose_model_v2(request: dict[str, Any], capabilities: list[ModelCapability]) -> tuple[ModelCapability, str]:
    eligible = eligible_models(request, capabilities)
    if not eligible:
        needs_tools = bool(request.get("tools") or request.get("tool_choice"))
        tokens = estimate_tokens(request)
        raise RuntimeError(f"No compatible model for request: needs_tools={needs_tools}, estimated_tokens={tokens}")

    policy = classify_v2_policy(request)
    eligible_by_name = {capability.model: capability for capability in eligible}
    for model in V2_POLICIES.get(policy, []):
        if model in eligible_by_name:
            return eligible_by_name[model], policy

    return choose_model(request, capabilities), f"{policy}:fallback-v1"


def choose_model_for_mode(request: dict[str, Any], capabilities: list[ModelCapability], mode: str) -> tuple[ModelCapability, str]:
    if mode == "v2":
        return choose_model_v2(request, capabilities)
    if mode == "v3":
        return choose_model_v2(request, capabilities)
    if mode == "v4":
        return choose_model_v2(request, capabilities)
    return choose_model(request, capabilities), "v1"


def classify_v4_route(request: dict[str, Any]) -> tuple[str, str]:
    tokens = estimate_tokens(request)
    text = extract_text_from_anthropic_messages(request.get("messages", [])).lower()
    has_tools = bool(request.get("tools") or request.get("tool_choice"))

    if has_tools:
        return "v2", "tools-need-single-driver"
    if tokens > 60000:
        return "v2", "long-context"
    # Hard reasoning / deduction / math -> single strong thinking model (v2 reasoning policy)
    if has_any_word(text, [
        "reason", "reasoning", "think step", "step by step", "analyze", "analyse",
        "strategy", "architect", "design pattern", "tradeoff", "trade off",
        "prove", "deduce", "math", "puzzle", "logic", "derive", "optimization",
        "algorithm", "complexity",
    ]):
        return "v2", "hard-reasoning"
    if any(
        phrase in text
        for phrase in [
            "compare",
            "tradeoff",
            "pros and cons",
            "best approach",
            "brainstorm",
            "synthesize",
            "strategy",
            "architecture",
            "explain deeply",
            "contrast",
            "design patterns",
            "how do you design",
            "what is the difference between"
        ]
    ):
        return "v3", "benefits-from-ensemble"
    if has_any_word(text, [
        "implement", "fix", "debug", "refactor", "test", "review", "audit", "regression", "diff", "lint", "vulnerability", "security",
        "code", "python", "javascript", "typescript", "golang", "rust", "function", "developer", "unittest", "pytest"
    ]):
        return "v2", "coding-or-review"
    if tokens < 1200:
        return "v1", "simple-fast-baseline"
    if has_any_word(text, ["summarize", "summary", "overview", "explain", "explain how", "why does", "what is"]):
        return "v2", "task-aware-summary"
    return "v2", "default-task-aware"


def ordered_fallback_models(request: dict[str, Any], capabilities: list[ModelCapability], preferred: ModelCapability) -> list[ModelCapability]:
    eligible = eligible_models(request, capabilities)
    by_name = {capability.model: capability for capability in eligible}
    ordered: list[ModelCapability] = []
    seen: set[str] = set()

    def add(candidate: ModelCapability | None) -> None:
        if candidate and candidate.model not in seen:
            ordered.append(candidate)
            seen.add(candidate.model)

    add(preferred)
    for model in V2_POLICIES.get(classify_v2_policy(request), []):
        add(by_name.get(model))
    for capability in eligible:
        add(capability)
    return ordered


# ─── Error classification + parallel race (storm-hardened fallback) ────────────
#
# The original fallback loop retried the SAME model 3× on 429 (sleeping 2s, 4s)
# and retried 4×/3× on deterministic 401/400 errors, producing 30–70s failure
# chains and broken pipes. These helpers classify errors so we:
#   • fail-fast on non-retryable auth/catalog errors (401/400/403/404/invalid key)
#   • never retry the same model on 429 (free-tier cooldown is model-wide; another
#     attempt seconds later still fails)
#   • race all eligible models in parallel on the first attempt so the winner is
#     the fastest healthy model and total latency ~= one round trip, not N×timeout.

_NONRETRYABLE_SUBSTRINGS = (
    "401", "authentication", "invalid api key", "invalid_api_key",
    "unauthorized", "forbidden", "403", "model_not_found", "not in the catalog",
    "400", "invalid_request", "bad request",
)
_RATELIMIT_SUBSTRINGS = (
    "429", "rate limit", "exhausted", "too many requests", "rate_limit",
)


def classify_upstream_error(exc_str: str) -> str:
    """Return one of: 'rate_limit', 'nonretryable', 'transient'."""
    low = (exc_str or "").lower()
    if any(kw in low for kw in _RATELIMIT_SUBSTRINGS):
        return "rate_limit"
    if any(kw in low for kw in _NONRETRYABLE_SUBSTRINGS):
        return "nonretryable"
    return "transient"


def _attempt_one_model(
    candidate: ModelCapability,
    payload: dict[str, Any],
    api_base: str,
    api_token: str | None,
    timeout: float = 12.0,
) -> tuple[ModelCapability, dict[str, Any] | None, str | None]:
    """Single attempt against one model. Returns (model, response, error_kind).

    On success response is set and error_kind is None.
    On failure response is None and error_kind is classify_upstream_error(exc_str).
    """
    try:
        response = http_json(
            "POST",
            join_v1_url(api_base, "/v1/chat/completions"),
            payload,
            api_token,
            timeout=timeout,
        )
        return candidate, response, None
    except Exception as exc:
        return candidate, None, classify_upstream_error(str(exc))


def race_models_for_first_success(
    request: dict[str, Any],
    candidates: list[ModelCapability],
    api_base: str,
    api_token: str | None,
    parallel: bool = True,
) -> tuple[dict[str, Any], ModelCapability, str]:
    """Storm-hardened fallback that HONORS PREFERENCE ORDER.

    Strategy:
      1. Try the preferred (first) candidate alone, with a tight timeout.
         This is the happy path — the strongest model for the task wins.
      2. If it fails (429/401/timeout), race the REMAINING candidates in parallel;
         first 200 wins. Non-retryable errors mark a model dead instantly.
      3. If all remaining are rate-limited, one short global backoff (2s) and one
         retry of the whole surviving set.
      4. If still nothing, raise RuntimeError with a compact failure summary.

    This keeps the happy path at one round-trip (preferred model), turns a
    401/429 storm into ~one failed round trip, and crucially picks the STRONGEST
    model for the task rather than the fastest weak one.
    """
    if not candidates:
        raise RuntimeError("No compatible fallback models available for this request.")

    failures: list[str] = []

    # Step 1: try the preferred (strongest) candidate first, alone.
    preferred = candidates[0]
    payload = anthropic_to_openai_payload(request, preferred.model)
    cand, response, err_kind = _attempt_one_model(preferred, payload, api_base, api_token, timeout=20.0)
    if response is not None:
        return response, cand, ""
    failures.append(f"{preferred.model}: {err_kind}")

    # Step 2: race the remaining candidates in parallel.
    rest = candidates[1:]

    def run_pass(alive: list[ModelCapability]) -> tuple[dict[str, Any], ModelCapability, list[str]] | None:
        local_failures: list[str] = []
        payloads = [(c, anthropic_to_openai_payload(request, c.model)) for c in alive]
        if parallel and len(alive) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(alive))) as ex:
                futures = {ex.submit(_attempt_one_model, c, p, api_base, api_token): c
                           for c, p in payloads}
                for fut in concurrent.futures.as_completed(futures):
                    cand, response, err_kind = fut.result()
                    if response is not None:
                        return response, cand, local_failures
                    local_failures.append(f"{cand.model}: {err_kind}")
        else:
            for cand, payload in payloads:
                c, response, err_kind = _attempt_one_model(cand, payload, api_base, api_token)
                if response is not None:
                    return response, c, local_failures
                local_failures.append(f"{cand.model}: {err_kind}")
        return None

    if rest:
        result = run_pass(rest)
        if result is not None:
            response, winner, local_failures = result
            failures.extend(local_failures)
            return response, winner, "; ".join(failures)

        # Step 3: all remaining rate-limited -> one short global backoff + retry.
        if all("rate_limit" in f for f in failures):
            time.sleep(2.0)
            result = run_pass(rest)
            if result is not None:
                response, winner, local_failures = result
                failures.extend(local_failures)
                return response, winner, "; ".join(failures)

    raise RuntimeError("All compatible fallback models failed: " + " | ".join(failures))


def post_with_model_fallback(
                request: dict[str, Any],
                capabilities: list[ModelCapability],
                preferred: ModelCapability,
                api_base: str,
                api_token: str | None,
) -> tuple[dict[str, Any], ModelCapability, str]:
                """Storm-hardened: race all eligible models in parallel, first 200 wins.

                Replaces the old sequential 3×-per-model retry loop. On a healthy upstream
                this is one round trip; on a 429/401 storm this fails in one round trip
                instead of burning 30–70s of same-model retries.
                """
                candidates = ordered_fallback_models(request, capabilities, preferred)
                return race_models_for_first_success(request, candidates, api_base, api_token, parallel=True)




def first_eligible_by_names(eligible: list[ModelCapability], names: list[str]) -> ModelCapability | None:
    by_name = {capability.model: capability for capability in eligible}
    for name in names:
        if name in by_name:
            return by_name[name]
    return None


def choose_v3_models(request: dict[str, Any], capabilities: list[ModelCapability]) -> tuple[list[ModelCapability], ModelCapability, str]:
    eligible = eligible_models(request, capabilities)
    if not eligible:
        needs_tools = bool(request.get("tools") or request.get("tool_choice"))
        tokens = estimate_tokens(request)
        raise RuntimeError(f"No compatible model for request: needs_tools={needs_tools}, estimated_tokens={tokens}")

    policy = classify_v2_policy(request)
    advisor_names = V2_POLICIES.get(policy, []) + [
        "mistral-large-3-675b",
        "command-a-reasoning",
        "kimi-k2.6",
        "nemotron-3-super-120b",
        "gpt-oss-120b",
        "llama-3.3-70b",
    ]
    aggregator_names = [
        "mistral-large-3-675b",
        "nemotron-3-super-120b",
        "gpt-oss-120b",
        "llama-3.3-70b",
    ]

    advisors: list[ModelCapability] = []
    seen: set[str] = set()
    eligible_by_name = {capability.model: capability for capability in eligible}
    for name in advisor_names:
        candidate = eligible_by_name.get(name)
        if candidate and candidate.model not in seen:
            advisors.append(candidate)
            seen.add(candidate.model)
        if len(advisors) >= 3:
            break
    if not advisors:
        advisors = eligible[:1]

    aggregator = first_eligible_by_names(eligible, aggregator_names) or advisors[0]
    return advisors, aggregator, policy


def run_v3_ensemble(request: dict[str, Any], capabilities: list[ModelCapability], api_base: str, api_token: str | None) -> tuple[dict[str, Any], str, str]:
    advisors, aggregator, policy = choose_v3_models(request, capabilities)
    original_text = extract_text_from_anthropic_messages(request.get("messages", []))
    advisor_outputs: list[tuple[str, str]] = []

    # Parallelize advisor gathering so v3 latency = max(advisors), not sum.
    # Each advisor gets a tight 12s timeout; failures are skipped (ensemble
    # degrades to fewer advisors rather than failing).
    def _gather(advisor: ModelCapability) -> tuple[str, str] | None:
        advisor_request = dict(request)
        advisor_request["max_tokens"] = min(int(request.get("max_tokens", 512)), 256)
        advisor_payload = anthropic_to_openai_payload(advisor_request, advisor.model)
        advisor_payload["messages"] = [
            {
                "role": "system",
                "content": (
                    "You are one advisor in a multi-model ensemble. "
                    "Give a concise, useful answer. Do not mention other advisors."
                ),
            },
            *advisor_payload.get("messages", []),
        ]
        try:
            advisor_response = http_json(
                "POST",
                join_v1_url(api_base, "/v1/chat/completions"),
                advisor_payload,
                api_token,
                timeout=12.0,
            )
            return (advisor.model, text_from_openai_response(advisor_response))
        except Exception:
            return None

    if len(advisors) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(advisors))) as ex:
            for res in ex.map(_gather, advisors):
                if res is not None:
                    advisor_outputs.append(res)
    else:
        res = _gather(advisors[0])
        if res is not None:
            advisor_outputs.append(res)

    if not advisor_outputs:
        fallback_response, fallback_model, _fallback_notes = post_with_model_fallback(
            request,
            capabilities,
            aggregator,
            api_base,
            api_token,
        )
        return openai_to_anthropic_response(fallback_response, fallback_model.model), f"{policy}:ensemble-fallback-single", fallback_model.model

    synthesis_lines = [
        "Synthesize the advisor outputs into one final answer.",
        "Be concise, resolve contradictions, and do not mention the ensemble unless asked.",
        "",
        "Original request:",
        original_text or "(no text extracted)",
        "",
        "Advisor outputs:",
    ]
    for model, output in advisor_outputs:
        synthesis_lines.append(f"\n[{model}]\n{output}")

    aggregator_request = {
        "model": request.get("model", aggregator.model),
        "messages": [{"role": "user", "content": "\n".join(synthesis_lines)}],
        "temperature": request.get("temperature", 0.2),
        "max_tokens": request.get("max_tokens", 512),
        "stream": False,
    }
    aggregator_response, final_aggregator, _fallback_notes = post_with_model_fallback(
        aggregator_request,
        capabilities,
        aggregator,
        api_base,
        api_token,
    )
    return openai_to_anthropic_response(aggregator_response, final_aggregator.model), policy, ",".join(model for model, _ in advisor_outputs)


def discover_model_rows(api_base: str, auth_token: str | None) -> list[dict[str, Any]]:
    response = http_json("GET", join_v1_url(api_base, "/v1/models"), auth_token=auth_token)
    data = response.get("data") or []
    return [item for item in data if isinstance(item, dict) and item.get("id")]


def discover_models(api_base: str, auth_token: str | None) -> list[str]:
    data = discover_model_rows(api_base, auth_token)
    models: list[str] = []
    for item in data:
        models.append(str(item["id"]))
    return models


def test_model(api_base: str, auth_token: str | None, model: str, known_context_window: int | None = None) -> ModelCapability:
    notes: list[str] = []
    supports_basic = False
    supports_tools = False
    context_window = known_context_window or 8192
    roles = ["summarization"]

    try:
        basic_payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly: ROUTER_MVP_OK"}],
            "temperature": 0,
            "max_tokens": 32,
        }
        response = http_json("POST", join_v1_url(api_base, "/v1/chat/completions"), basic_payload, auth_token)
        text = ((response.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        supports_basic = "ROUTER_MVP_OK" in text or bool(text)
    except Exception as exc:
        notes.append(f"basic chat failed: {exc}")

    try:
        tool_payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Call the ping tool with value ok."}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "ping",
                        "description": "Test tool",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                        },
                    },
                }
            ],
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": 64,
        }
        response = http_json("POST", join_v1_url(api_base, "/v1/chat/completions"), tool_payload, auth_token)
        message = ((response.get("choices") or [{}])[0].get("message") or {})
        supports_tools = bool(message.get("tool_calls"))
    except Exception as exc:
        notes.append(f"tool call failed: {exc}")

    if supports_tools:
        roles = ["coding", "tool_use", "summarization"]

    if known_context_window is None and ("long" in model.lower() or "32" in model or "70" in model):
        context_window = 32768
    if "code" in model.lower():
        roles = sorted(set(roles + ["coding"]))

    return ModelCapability(
        model=model,
        claude_code_compatible=supports_basic and supports_tools,
        supports_tools=supports_tools,
        supports_streaming=False,
        context_window=context_window,
        roles=roles,
        notes="; ".join(notes),
    )


class MockFreeLLMHandler(BaseHTTPRequestHandler):
    server_version = "MockFreeLLM/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("MVP_VERBOSE"):
            super().log_message(fmt, *args)

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/v1/models":
            write_json(
                self,
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": "free-summary-fast", "object": "model"},
                        {"id": "free-code-tools", "object": "model"},
                        {"id": "free-broken-text-only", "object": "model"},
                    ],
                },
            )
            return
        write_json(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path != "/v1/chat/completions":
            write_json(self, 404, {"error": "not found"})
            return

        body = read_json_body(self)
        model = body.get("model", "")
        messages = body.get("messages") or []
        prompt = "\n".join(str(message.get("content", "")) for message in messages)
        tools = body.get("tools") or []

        if model == "free-broken-text-only":
            write_json(self, 500, {"error": "model unavailable"})
            return

        if tools and model == "free-code-tools":
            tool_name = tools[0].get("function", {}).get("name", "ping")
            content = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_mock_1",
                        "type": "function",
                        "function": {"name": tool_name, "arguments": json.dumps({"value": "ok"})},
                    }
                ],
            }
        elif tools:
            content = {"role": "assistant", "content": "I cannot call tools reliably."}
        elif "ROUTER_MVP_OK" in prompt:
            content = {"role": "assistant", "content": "ROUTER_MVP_OK"}
        elif "summarize" in prompt.lower():
            content = {"role": "assistant", "content": f"Summary from {model}: this is a compact answer."}
        else:
            content = {"role": "assistant", "content": f"Response from {model}: routed successfully."}

        write_json(
            self,
            200,
            {
                "id": f"chatcmpl_mock_{int(time.time() * 1000)}",
                "object": "chat.completion",
                "model": model,
                "choices": [{"index": 0, "message": content, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": max(1, len(prompt) // 4), "completion_tokens": 12},
            },
        )


def get_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FreeLLM Claude Router Control Panel</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(22, 28, 45, 0.6);
            --border-color: rgba(255, 255, 255, 0.08);
            --primary-glow: linear-gradient(135deg, #7c3aed 0%, #3b82f6 100%);
            --text-color: #f3f4f6;
            --text-muted: #9ca3af;
            --accent-purple: #8b5cf6;
            --accent-blue: #3b82f6;
            --status-success: #10b981;
            --status-error: #ef4444;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(124, 58, 237, 0.05) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(59, 130, 246, 0.05) 0%, transparent 40%);
        }

        header {
            border-bottom: 1px solid var(--border-color);
            padding: 1.5rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            backdrop-filter: blur(12px);
            background: rgba(11, 15, 25, 0.8);
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .logo-section {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .logo-indicator {
            width: 12px;
            height: 12px;
            background: var(--primary-glow);
            border-radius: 50%;
            box-shadow: 0 0 12px var(--accent-purple);
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.9); opacity: 0.6; }
            50% { transform: scale(1.1); opacity: 1; box-shadow: 0 0 16px var(--accent-blue); }
            100% { transform: scale(0.9); opacity: 0.6; }
        }

        h1 {
            font-size: 1.25rem;
            font-weight: 700;
            letter-spacing: -0.5px;
            background: linear-gradient(to right, #ffffff, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        main {
            flex: 1;
            max-width: 1200px;
            width: 100%;
            margin: 0 auto;
            padding: 2rem;
            display: flex;
            flex-direction: column;
            gap: 2rem;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1.5rem;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            backdrop-filter: blur(8px);
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.2);
            transition: transform 0.2s, border-color 0.2s;
        }

        .card:hover {
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.15);
        }

        .stats-label {
            font-size: 0.875rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.5rem;
        }

        .stats-val {
            font-size: 2.25rem;
            font-weight: 700;
            letter-spacing: -1px;
        }

        .mode-container {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .mode-title-sec {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .mode-selector {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            padding: 0.25rem;
            border-radius: 12px;
            gap: 0.25rem;
        }

        .mode-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 0.75rem 1rem;
            border-radius: 8px;
            font-weight: 600;
            font-family: inherit;
            cursor: pointer;
            transition: all 0.2s;
        }

        .mode-btn:hover {
            color: var(--text-color);
            background: rgba(255, 255, 255, 0.05);
        }

        .mode-btn.active {
            background: var(--primary-glow);
            color: #ffffff;
            box-shadow: 0 4px 12px rgba(124, 58, 237, 0.3);
        }

        .mode-desc {
            font-size: 0.875rem;
            color: var(--text-muted);
            margin-top: 0.5rem;
        }

        .history-section {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .section-title {
            font-size: 1.1rem;
            font-weight: 600;
        }

        .table-container {
            width: 100%;
            overflow-x: auto;
            border: 1px solid var(--border-color);
            border-radius: 12px;
            background: var(--card-bg);
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.875rem;
        }

        th, td {
            padding: 1rem;
            border-bottom: 1px solid var(--border-color);
        }

        th {
            background: rgba(255, 255, 255, 0.02);
            font-weight: 600;
            color: var(--text-muted);
        }

        tr:last-child td {
            border-bottom: none;
        }

        .badge {
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.5rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }

        .badge-success {
            background: rgba(16, 185, 129, 0.15);
            color: var(--status-success);
        }

        .badge-error {
            background: rgba(239, 68, 68, 0.15);
            color: var(--status-error);
        }

        .badge-info {
            background: rgba(59, 130, 246, 0.15);
            color: var(--accent-blue);
        }

        .latency-bar {
            height: 6px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 3px;
            overflow: hidden;
            width: 80px;
            display: inline-block;
            vertical-align: middle;
            margin-right: 0.5rem;
        }

        .latency-progress {
            height: 100%;
            background: var(--accent-blue);
            border-radius: 3px;
        }

        .no-data {
            text-align: center;
            color: var(--text-muted);
            padding: 3rem;
        }
    </style>
</head>
<body>
    <header>
        <div class="logo-section">
            <div class="logo-indicator"></div>
            <h1>FreeLLM Router Control Panel</h1>
        </div>
        <div id="connection-status" class="badge badge-success">Online</div>
    </header>

    <main>
        <div class="stats-grid">
            <div class="card">
                <div class="stats-label">Total Requests</div>
                <div class="stats-val" id="total-requests">0</div>
            </div>
            <div class="card">
                <div class="stats-label">Success Rate</div>
                <div class="stats-val" id="success-rate">0%</div>
            </div>
            <div class="card">
                <div class="stats-label">Avg Latency</div>
                <div class="stats-val" id="avg-latency">0ms</div>
            </div>
        </div>

        <div class="card mode-container">
            <div class="mode-title-sec">
                <div class="section-title">Router Version Mode</div>
                <div class="badge badge-info" id="current-mode-badge">MODE: v2</div>
            </div>
            <div class="mode-selector">
                <button class="mode-btn" onclick="updateMode('v1')" id="btn-v1">v1 (Single)</button>
                <button class="mode-btn" onclick="updateMode('v2')" id="btn-v2">v2 (Task-Aware)</button>
                <button class="mode-btn" onclick="updateMode('v3')" id="btn-v3">v3 (Ensemble)</button>
                <button class="mode-btn" onclick="updateMode('v4')" id="btn-v4">v4 (Meta)</button>
            </div>
            <div class="mode-desc" id="mode-explanation">
                Loading mode details...
            </div>
        </div>

        <div class="history-section">
            <div class="section-header">
                <div class="section-title">Recent Routing Decisions (Last 50)</div>
                <button class="mode-btn" onclick="fetchDecisions()" style="padding:0.4rem 0.8rem; font-size:0.8rem; border:1px solid var(--border-color); border-radius:6px;">Refresh Now</button>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Timestamp</th>
                            <th>Mode</th>
                            <th>Matched Policy</th>
                            <th>Target Model</th>
                            <th>Latency</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody id="decisions-body">
                        <tr>
                            <td colspan="6" class="no-data">Loading decisions...</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <script>
        const EXPLANATIONS = {
            v1: "Version 1 runs queries directly against the single default model, bypassing task-aware routing policies.",
            v2: "Version 2 analyzes the task complexity, system tools, and prompt tags to route to the most optimal coding, summarization, or review model.",
            v3: "Version 3 runs parallel queries to multiple advisor models (GPT-OSS, Llama 3.3) and synthesizes their feedback to generate high-quality critiques.",
            v4: "Version 4 (Meta-Router) automatically dynamically decides whether to use a fast, cheap single model (v2) or route to the expensive ensemble model (v3)."
        };

        let activeMode = 'v1';

        async function fetchConfig() {
            try {
                const res = await fetch('/api/config');
                const config = await res.json();
                setActiveModeBtn(config.mode);
            } catch (err) {
                console.error("Failed to fetch config", err);
                document.getElementById('connection-status').className = "badge badge-error";
                document.getElementById('connection-status').textContent = "Offline";
            }
        }

        function setActiveModeBtn(mode) {
            activeMode = mode;
            document.querySelectorAll('.mode-btn').forEach(btn => btn.classList.remove('active'));
            const btn = document.getElementById('btn-' + mode);
            if (btn) btn.classList.add('active');
            document.getElementById('current-mode-badge').textContent = 'MODE: ' + mode.toUpperCase();
            document.getElementById('mode-explanation').textContent = EXPLANATIONS[mode] || '';
        }

        async function updateMode(mode) {
            try {
                const res = await fetch('/api/config/update', {
                    method: 'POST',
                    headers: {'content-type': 'application/json'},
                    body: JSON.stringify({mode})
                });
                const data = await res.json();
                if (data.ok) {
                    setActiveModeBtn(mode);
                }
            } catch (err) {
                console.error("Failed to update mode", err);
            }
        }

        async function fetchDecisions() {
            try {
                const res = await fetch('/api/decisions');
                const data = await res.json();
                renderDecisions(data.decisions);
            } catch (err) {
                console.error("Failed to fetch decisions", err);
            }
        }

        function renderDecisions(decisions) {
            const body = document.getElementById('decisions-body');
            if (!decisions || decisions.length === 0) {
                body.innerHTML = '<tr><td colspan="6" class="no-data">No routing decisions logged yet.</td></tr>';
                return;
            }

            // Calculate stats
            const total = decisions.length;
            const successCount = decisions.filter(d => d.status === 'success').length;
            const successRate = total > 0 ? Math.round((successCount / total) * 100) : 0;
            const latencies = decisions.filter(d => d.latency_ms !== undefined).map(d => d.latency_ms);
            const avgLatency = latencies.length > 0 ? Math.round(latencies.reduce((a,b) => a+b, 0) / latencies.length) : 0;

            document.getElementById('total-requests').textContent = total;
            document.getElementById('success-rate').textContent = successRate + '%';
            document.getElementById('avg-latency').textContent = avgLatency + 'ms';

            body.innerHTML = '';
            // Show recent decisions first
            [...decisions].reverse().forEach(dec => {
                const tr = document.createElement('tr');
                
                const time = dec.timestamp ? new Date(dec.timestamp).toLocaleTimeString() : 'N/A';
                const mode = dec.mode || 'v1';
                const policy = dec.policy || 'none';
                const model = dec.selected_model || 'N/A';
                const latency = dec.latency_ms !== undefined ? dec.latency_ms + 'ms' : 'N/A';
                
                const statusBadge = dec.status === 'success' 
                    ? '<span class="badge badge-success">Success</span>' 
                    : `<span class="badge badge-error" title="${dec.error_message || ''}">Error</span>`;

                const maxLatencyForBar = 8000;
                const percentage = dec.latency_ms ? Math.min(100, (dec.latency_ms / maxLatencyForBar) * 100) : 0;

                tr.innerHTML = `
                    <td>${time}</td>
                    <td><span class="badge badge-info">${mode}</span></td>
                    <td><code>${policy}</code></td>
                    <td><span style="font-weight:600;">${model}</span></td>
                    <td>
                        <div class="latency-bar">
                            <div class="latency-progress" style="width: ${percentage}%;"></div>
                        </div>
                        ${latency}
                    </td>
                    <td>${statusBadge}</td>
                `;
                body.appendChild(tr);
            });
        }

        // Init and Poll
        fetchConfig();
        fetchDecisions();
        setInterval(fetchConfig, 3000);
        setInterval(fetchDecisions, 3000);
    </script>
</body>
</html>"""


def stream_openai_to_anthropic(
    openai_response: http.client.HTTPResponse,
    handler: BaseHTTPRequestHandler,
    model_name: str,
) -> None:
    message_id = f"msg_mvp_{int(time.time())}"
    write_sse(handler, "message_start", {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": model_name,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}
        }
    })
    
    current_content_type = None
    current_index = 0
    
    for line_bytes in openai_response:
        line = line_bytes.decode("utf-8").strip()
        if not line:
            continue
        if line.startswith("data:"):
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta", {})
                
                # Text Content
                if "content" in delta and delta["content"]:
                    text_chunk = delta["content"]
                    if current_content_type != "text":
                        if current_content_type is not None:
                            write_sse(handler, "content_block_stop", {"type": "content_block_stop", "index": current_index})
                            current_index += 1
                        current_content_type = "text"
                        write_sse(handler, "content_block_start", {
                            "type": "content_block_start",
                            "index": current_index,
                            "content_block": {"type": "text", "text": ""}
                        })
                    
                    write_sse(handler, "content_block_delta", {
                        "type": "content_block_delta",
                        "index": current_index,
                        "delta": {"type": "text_delta", "text": text_chunk}
                    })
                    
                # Tool Call Content
                elif "tool_calls" in delta and delta["tool_calls"]:
                    tool_call = delta["tool_calls"][0]
                    func = tool_call.get("function", {})
                    
                    if current_content_type != "tool_use":
                        if current_content_type is not None:
                            write_sse(handler, "content_block_stop", {"type": "content_block_stop", "index": current_index})
                            current_index += 1
                        current_content_type = "tool_use"
                        tool_id = tool_call.get("id") or f"toolu_mvp_{int(time.time())}"
                        tool_name = func.get("name", "tool")
                        
                        write_sse(handler, "content_block_start", {
                            "type": "content_block_start",
                            "index": current_index,
                            "content_block": {
                                "type": "tool_use",
                                "id": tool_id,
                                "name": tool_name,
                                "input": {}
                            }
                        })
                        
                    if "arguments" in func:
                        arg_chunk = func["arguments"]
                        write_sse(handler, "content_block_delta", {
                            "type": "content_block_delta",
                            "index": current_index,
                            "delta": {"type": "input_json_delta", "partial_json": arg_chunk}
                        })
                        
            except Exception as e:
                pass
                
    if current_content_type is not None:
        write_sse(handler, "content_block_stop", {"type": "content_block_stop", "index": current_index})
        
    write_sse(handler, "message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 0}
    })
    write_sse(handler, "message_stop", {"type": "message_stop"})


def post_stream_with_model_fallback(
    request: dict[str, Any],
    capabilities: list[ModelCapability],
    preferred: ModelCapability,
    api_base: str,
    api_token: str | None,
    handler: BaseHTTPRequestHandler,
) -> tuple[ModelCapability, str]:
    """Storm-hardened streaming fallback.

    Streaming can't race across models (headers are already committed once the
    first byte is written), so we walk candidates sequentially but FAIL FAST:
    no same-model retry on 429, no retries at all on 401/400/non-retryable, and
    a short 12s per-attempt timeout. On a healthy upstream this is one round
    trip; on a storm it fails in one pass per model instead of 3× with sleeps.
    """
    failures: list[str] = []
    parsed = urllib.parse.urlparse(api_base)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    base_path = parsed.path or "/"
    if base_path.endswith("/"):
        base_path = base_path[:-1]
    target_path = base_path + "/chat/completions"
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    for candidate in ordered_fallback_models(request, capabilities, preferred):
        upstream_payload = anthropic_to_openai_payload(request, candidate.model)
        upstream_payload["stream"] = True
        headers = {"content-type": "application/json"}
        if api_token:
            headers["authorization"] = f"Bearer {api_token}"

        try:
            conn = conn_cls(host, port, timeout=15)
            conn.request("POST", target_path, body=json.dumps(upstream_payload).encode("utf-8"), headers=headers)
            response = conn.getresponse()

            if response.status != 200:
                resp_body = response.read()
                conn.close()
                err_kind = classify_upstream_error(f"HTTP {response.status}: {resp_body}")
                failures.append(f"{candidate.model}: {err_kind}")
                # non-retryable (401/400/404) or rate-limit: skip to next model, no same-model retry
                continue

            handler.send_response(200)
            handler.send_header("content-type", "text/event-stream")
            handler.send_header("cache-control", "no-cache")
            handler.send_header("connection", "close")
            handler.end_headers()
            handler.close_connection = True

            stream_openai_to_anthropic(response, handler, candidate.model)
            conn.close()
            return candidate, "; ".join(failures)

        except Exception as exc:
            err_kind = classify_upstream_error(str(exc))
            failures.append(f"{candidate.model}: {err_kind}")
            try:
                conn.close()
            except Exception:
                pass
            continue

    raise RuntimeError("All compatible fallback models failed: " + " | ".join(failures))


class RouterProxyHandler(BaseHTTPRequestHandler):
    server_version = "FreeLLMRouterProxy/0.1"
    api_base = "http://127.0.0.1:8091"
    api_token: str | None = None
    allowlist_path = DEFAULT_ALLOWLIST_PATH
    mode = "v1"

    def log_message(self, fmt: str, *args: Any) -> None:
        super().log_message(fmt, *args)

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/dashboard":
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(get_dashboard_html().encode("utf-8"))
            return
        if path == "/api/decisions":
            decisions = []
            try:
                with log_lock:
                    if os.path.exists(DECISION_LOG_PATH):
                        with open(DECISION_LOG_PATH, "r", encoding="utf-8") as f:
                            lines = f.readlines()
                            for line in lines[-50:]:
                                try:
                                    decisions.append(json.loads(line))
                                except:
                                    pass
            except Exception as e:
                print(f"Error reading decisions: {e}", file=sys.stderr)
            write_json(self, 200, {"decisions": decisions})
            return
        if path == "/api/config":
            capabilities = []
            try:
                capabilities = [
                    {"model": cap.model, "claudeCodeCompatible": cap.claude_code_compatible}
                    for cap in load_allowlist(self.allowlist_path)
                ]
            except:
                pass
            write_json(self, 200, {
                "mode": RouterProxyHandler.mode,
                "allowlist": capabilities
            })
            return
        if path in {"/", "/health"}:
            write_json(self, 200, {"ok": True})
            return
        if path == "/v1/models":
            capabilities = load_allowlist(self.allowlist_path)
            compatible = [
                {"id": capability.model, "type": "model", "display_name": capability.model}
                for capability in capabilities
                if capability.claude_code_compatible
            ]
            write_json(
                self,
                200,
                {
                    "data": [
                        {"id": "router-auto", "type": "model", "display_name": "Router Auto"},
                        *compatible,
                    ]
                },
            )
            return
        write_json(self, 404, {"error": "not found"})

    def do_HEAD(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path in {"/", "/health", "/v1/models", "/dashboard", "/api/decisions", "/api/config"}:
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/config/update":
            data = read_json_body(self)
            new_mode = data.get("mode")
            if new_mode in {"v1", "v2", "v3", "v4"}:
                RouterProxyHandler.mode = new_mode
                write_json(self, 200, {"ok": True, "mode": new_mode})
            else:
                write_json(self, 400, {"error": "invalid mode"})
            return
        if path == "/v1/messages/count_tokens":
            request = read_json_body(self)
            write_json(self, 200, {"input_tokens": estimate_tokens(request)})
            return
        if path != "/v1/messages":
            write_json(self, 404, {"error": "not found"})
            return
        
        start_time = time.time()
        effective_mode = self.mode
        route_reason = ""
        request = {}
        api_token = self.api_token
        auth_header = self.headers.get("authorization")
        if not api_token and auth_header and auth_header.lower().startswith("bearer "):
            api_token = auth_header[7:]
        try:
            request = read_json_body(self)
            capabilities = load_allowlist(self.allowlist_path)
            if self.mode == "v4":
                effective_mode, route_reason = classify_v4_route(request)

            if effective_mode == "v3" and not (request.get("tools") or request.get("tool_choice")):
                anthropic_response, policy, advisor_models = run_v3_ensemble(
                    request,
                    capabilities,
                    self.api_base,
                    api_token,
                )
                latency_ms = int((time.time() - start_time) * 1000)
                
                # Log success
                log_decision({
                    "mode": self.mode,
                    "effective_mode": effective_mode,
                    "route_reason": route_reason,
                    "policy": f"ensemble:{policy}",
                    "selected_model": anthropic_response.get("model", ""),
                    "advisors": advisor_models,
                    "input_tokens": estimate_tokens(request),
                    "output_tokens": anthropic_response.get("usage", {}).get("output_tokens", 0),
                    "latency_ms": latency_ms,
                    "status": "success"
                })

                if request.get("stream") is True:
                    write_anthropic_stream(self, anthropic_response)
                    return
                write_json(
                    self,
                    200,
                    anthropic_response,
                    headers={
                        "x-router-selected-model": anthropic_response.get("model", ""),
                        "x-router-mode": self.mode,
                        "x-router-selected-version": effective_mode,
                        "x-router-policy": f"ensemble:{policy}",
                        "x-router-route-reason": route_reason,
                        "x-router-advisor-models": advisor_models,
                    },
                )
                return

            selected, policy = choose_model_for_mode(request, capabilities, effective_mode)
            if request.get("stream") is True:
                final_model, fallback_notes = post_stream_with_model_fallback(
                    request,
                    capabilities,
                    selected,
                    self.api_base,
                    api_token,
                    self,
                )
                latency_ms = int((time.time() - start_time) * 1000)
                log_decision({
                    "mode": self.mode,
                    "effective_mode": effective_mode,
                    "route_reason": route_reason,
                    "policy": policy,
                    "selected_model": final_model.model,
                    "fallback_notes": fallback_notes,
                    "input_tokens": estimate_tokens(request),
                    "output_tokens": 0,
                    "latency_ms": latency_ms,
                    "status": "success"
                })
                return

            upstream_response, final_model, fallback_notes = post_with_model_fallback(
                request,
                capabilities,
                selected,
                self.api_base,
                api_token,
            )
            anthropic_response = openai_to_anthropic_response(upstream_response, final_model.model)
            latency_ms = int((time.time() - start_time) * 1000)

            # Log success
            log_decision({
                "mode": self.mode,
                "effective_mode": effective_mode,
                "route_reason": route_reason,
                "policy": policy,
                "selected_model": final_model.model,
                "fallback_notes": fallback_notes,
                "input_tokens": estimate_tokens(request),
                "output_tokens": anthropic_response.get("usage", {}).get("output_tokens", 0),
                "latency_ms": latency_ms,
                "status": "success"
            })

            headers = {
                "x-router-selected-model": final_model.model,
                "x-router-mode": self.mode,
                "x-router-selected-version": effective_mode,

                "x-router-policy": policy,
                "x-router-route-reason": route_reason,
            }
            if fallback_notes:
                headers["x-router-fallbacks"] = fallback_notes[:800]
            write_json(
                self,
                200,
                anthropic_response,
                headers=headers,
            )
        except Exception as exc:
            latency_ms = int((time.time() - start_time) * 1000)
            if os.environ.get("MVP_VERBOSE"):
                traceback.print_exc()
            
            # Log error
            log_decision({
                "mode": self.mode,
                "effective_mode": effective_mode,
                "route_reason": route_reason,
                "input_tokens": estimate_tokens(request) if request else 0,
                "latency_ms": latency_ms,
                "status": "error",
                "error_message": str(exc)
            })

            write_json(self, 502, {"type": "error", "error": {"type": "router_error", "message": str(exc)}})


def serve(handler_cls: type[BaseHTTPRequestHandler], host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def parse_model_filter(models_csv: str | None) -> list[str] | None:
    if not models_csv:
        return None
    models = [item.strip() for item in models_csv.split(",") if item.strip()]
    return models or None


def run_probe(
    api_base: str,
    auth_token: str | None,
    output_path: str,
    model_filter: list[str] | None = None,
    max_models: int | None = None,
) -> list[ModelCapability]:
    discovered_rows = discover_model_rows(api_base, auth_token)
    context_windows = {
        str(item["id"]): int(item["context_window"])
        for item in discovered_rows
        if item.get("context_window") is not None
    }
    models = model_filter if model_filter is not None else [str(item["id"]) for item in discovered_rows]
    models = [model for model in models if model != "auto"]
    if max_models is not None:
        models = models[:max_models]
    if not models:
        raise RuntimeError(f"No models discovered from {api_base}/v1/models")
    capabilities = [test_model(api_base, auth_token, model, context_windows.get(model)) for model in models]
    save_allowlist(output_path, capabilities)
    return capabilities


def run_proxy(api_base: str, api_token: str | None, allowlist_path: str, host: str, port: int, mode: str) -> None:
    RouterProxyHandler.api_base = api_base
    RouterProxyHandler.api_token = api_token
    RouterProxyHandler.allowlist_path = allowlist_path
    RouterProxyHandler.mode = mode
    server = ThreadingHTTPServer((host, port), RouterProxyHandler)

    def stop(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f"Router proxy listening on http://{host}:{port}")
    print(f"Router mode: {mode}")
    print(f"Set ANTHROPIC_BASE_URL=http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nRouter proxy stopped")
    finally:
        server.server_close()


def demo(base_dir: str) -> None:
    allowlist_path = os.path.join(base_dir, DEFAULT_ALLOWLIST_PATH)
    mock_server = serve(MockFreeLLMHandler, "127.0.0.1", 0)
    mock_base = f"http://127.0.0.1:{mock_server.server_address[1]}"
    try:
        capabilities = run_probe(mock_base, None, allowlist_path)
        compatible = [capability.model for capability in capabilities if capability.claude_code_compatible]
        print("Compatible models:", ", ".join(compatible))
        assert compatible == ["free-code-tools"], compatible

        RouterProxyHandler.api_base = mock_base
        RouterProxyHandler.api_token = None
        RouterProxyHandler.allowlist_path = allowlist_path
        proxy_server = serve(RouterProxyHandler, "127.0.0.1", 0)
        proxy_base = f"http://127.0.0.1:{proxy_server.server_address[1]}"
        try:
            summary = http_json(
                "POST",
                proxy_base + "/v1/messages",
                {
                    "model": "router-auto",
                    "max_tokens": 128,
                    "messages": [{"role": "user", "content": "Summarize this MVP in one sentence."}],
                },
            )
            assert summary["model"] == "free-code-tools"
            assert summary["content"][0]["type"] == "text"

            tool_response = http_json(
                "POST",
                proxy_base + "/v1/messages",
                {
                    "model": "router-auto",
                    "max_tokens": 128,
                    "messages": [{"role": "user", "content": "Use ping."}],
                    "tools": [
                        {
                            "name": "ping",
                            "description": "Test tool",
                            "input_schema": {
                                "type": "object",
                                "properties": {"value": {"type": "string"}},
                                "required": ["value"],
                            },
                        }
                    ],
                },
            )
            assert tool_response["model"] == "free-code-tools"
            assert any(block["type"] == "tool_use" for block in tool_response["content"])
            print("Demo passed: proxy discovered, filtered, and routed to a Claude-Code-compatible model.")
            print(f"Allowlist written to {allowlist_path}")
        finally:
            proxy_server.shutdown()
    finally:
        mock_server.shutdown()


def smoke(base_dir: str) -> None:
    """Run a user-facing local smoke test and print the key evidence."""
    allowlist_path = os.path.join(base_dir, DEFAULT_ALLOWLIST_PATH)
    mock_server = serve(MockFreeLLMHandler, "127.0.0.1", 0)
    mock_base = f"http://127.0.0.1:{mock_server.server_address[1]}"
    try:
        capabilities = run_probe(mock_base, None, allowlist_path)
        compatible = [capability.model for capability in capabilities if capability.claude_code_compatible]
        print("1. Probe complete")
        print("   Compatible models:", ", ".join(compatible) or "(none)")

        RouterProxyHandler.api_base = mock_base
        RouterProxyHandler.api_token = None
        RouterProxyHandler.allowlist_path = allowlist_path
        proxy_server = serve(RouterProxyHandler, "127.0.0.1", 0)
        proxy_base = f"http://127.0.0.1:{proxy_server.server_address[1]}"
        try:
            models = http_json("GET", proxy_base + "/v1/models")
            print("2. Proxy model list")
            print("   " + ", ".join(item["id"] for item in models.get("data", [])))

            summary = http_json(
                "POST",
                proxy_base + "/v1/messages",
                {
                    "model": "router-auto",
                    "max_tokens": 128,
                    "messages": [{"role": "user", "content": "Summarize this MVP in one sentence."}],
                },
            )
            print("3. Text request routed")
            print(f"   selected model: {summary['model']}")
            print(f"   response type: {summary['content'][0]['type']}")

            token_count = http_json(
                "POST",
                proxy_base + "/v1/messages/count_tokens",
                {
                    "model": "router-auto",
                    "messages": [{"role": "user", "content": "Count this small request."}],
                },
            )
            print("4. Claude token-count endpoint")
            print(f"   estimated input tokens: {token_count['input_tokens']}")

            tool_response = http_json(
                "POST",
                proxy_base + "/v1/messages",
                {
                    "model": "router-auto",
                    "max_tokens": 128,
                    "messages": [{"role": "user", "content": "Use ping."}],
                    "tools": [
                        {
                            "name": "ping",
                            "description": "Test tool",
                            "input_schema": {
                                "type": "object",
                                "properties": {"value": {"type": "string"}},
                                "required": ["value"],
                            },
                        }
                    ],
                },
            )
            tool_blocks = [block for block in tool_response["content"] if block["type"] == "tool_use"]
            assert compatible == ["free-code-tools"], compatible
            assert summary["model"] == "free-code-tools"
            assert token_count["input_tokens"] > 0
            assert tool_blocks and tool_blocks[0]["name"] == "ping"
            print("5. Tool request routed")
            print(f"   selected model: {tool_response['model']}")
            print(f"   tool block: {json.dumps(tool_blocks[0])}")
            print("")
            print("Smoke test passed.")
            print(f"Allowlist written to {allowlist_path}")
        finally:
            proxy_server.shutdown()
    finally:
        mock_server.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="FreeLLM Claude Code router MVP")
    subcommands = parser.add_subparsers(dest="command", required=True)

    probe_parser = subcommands.add_parser("probe", help="Probe models and create an allowlist")
    probe_parser.add_argument("--api-base", default=os.environ.get("FREE_LLM_API_BASE", DEFAULT_MOCK_BASE))
    probe_parser.add_argument("--api-token", default=os.environ.get("FREE_LLM_API_TOKEN"))
    probe_parser.add_argument("--output", default=DEFAULT_ALLOWLIST_PATH)
    probe_parser.add_argument("--models", help="Comma-separated model IDs to probe instead of every /v1/models entry")
    probe_parser.add_argument("--max-models", type=int, help="Probe at most this many model IDs")

    proxy_parser = subcommands.add_parser("proxy", help="Run Anthropic-compatible routing proxy")
    proxy_parser.add_argument("--api-base", default=os.environ.get("FREE_LLM_API_BASE", DEFAULT_MOCK_BASE))
    proxy_parser.add_argument("--api-token", default=os.environ.get("FREE_LLM_API_TOKEN"))
    proxy_parser.add_argument("--allowlist", default=DEFAULT_ALLOWLIST_PATH)
    proxy_parser.add_argument("--host", default="127.0.0.1")
    proxy_parser.add_argument("--port", type=int, default=8787)
    proxy_parser.add_argument("--mode", choices=["v1", "v2", "v3", "v4"], default=os.environ.get("CLAUDE_ROUTER_MODE", "v1"))

    mock_parser = subcommands.add_parser("mock-freellm", help="Run mock OpenAI-compatible FreeLLM API")
    mock_parser.add_argument("--host", default="127.0.0.1")
    mock_parser.add_argument("--port", type=int, default=8091)

    demo_parser = subcommands.add_parser("demo", help="Run end-to-end local proof")
    demo_parser.add_argument("--base-dir", default=os.getcwd())

    smoke_parser = subcommands.add_parser("smoke", help="Run a readable one-command local smoke test")
    smoke_parser.add_argument("--base-dir", default=os.getcwd())

    args = parser.parse_args()

    if args.command == "probe":
        capabilities = run_probe(
            args.api_base,
            args.api_token,
            args.output,
            parse_model_filter(args.models),
            args.max_models,
        )
        print(json.dumps({"models": [capability.as_json() for capability in capabilities]}, indent=2))
        return 0
    if args.command == "proxy":
        run_proxy(args.api_base, args.api_token, args.allowlist, args.host, args.port, args.mode)
        return 0
    if args.command == "mock-freellm":
        server = ThreadingHTTPServer((args.host, args.port), MockFreeLLMHandler)
        print(f"Mock FreeLLM API listening on http://{args.host}:{args.port}")
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
        return 0
    if args.command == "demo":
        demo(args.base_dir)
        return 0
    if args.command == "smoke":
        smoke(args.base_dir)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
