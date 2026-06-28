#!/usr/bin/env python3
"""
Voice Router — a speed-first, OpenAI-format routing proxy for the Thrivbe Voice Agent (Rachel).

WHY THIS EXISTS (separate from freellm_router_mvp.py):
  The Claude Code router (freellm_router_mvp.py) is optimized for INTELLIGENCE —
  it picks the strongest model per task (mistral-large-3-675b, a 675B model that
  takes 2–9s) and speaks Anthropic format. The voice agent has the OPPOSITE needs:
    • Latency is king — must feel conversational (<3s to first byte)
    • It speaks OpenAI /v1/chat/completions, not Anthropic /v1/messages
    • Most requests carry tools (phone control, CRM, search) → need a FAST tool-capable model
    • Output is short + spoken (no long structured answers)
  So this router optimizes for SPEED: fast tool-capable models first, only escalate to a
  slow thinking model when the user explicitly asks for analysis/strategy/comparison.

ARCHITECTURE:
  Voice Agent (server.py)
    -> Voice Router (this file, port 8793)  [OpenAI-format, speed-first]
      -> FreeLLMAPI (port 3004)              [OpenAI-compatible, provider fallback]

ROUTING (speed-first):
  tools present            -> llama-3.3-70b   (fast, tool-capable)
  plain short chat         -> gpt-oss-20b     (fast)
  explicit reasoning       -> mistral-large-3-675b (smart, slower — only when needed)
  long context (>60k tok)  -> nemotron-3-super-120b (1M ctx)
  fallback                 -> race remaining fast models in parallel

STORM HARDENING (same as the Claude Code router):
  • Preferred (fastest) model tried first, alone.
  • On failure, race remaining models in parallel; first 200 wins.
  • Fail-fast on 401/400/403/404 (non-retryable); no same-model retry on 429.
  • Turns a 429/401 storm into ~one failed round trip, not a 30–70s hang.

STREAMING:
  Pass-through SSE. If the client sends stream:true, the router streams the
  upstream OpenAI SSE straight back so TTS can start speaking the first sentence
  before the model finishes generating.

Usage:
  python3 voice_router_mvp.py proxy \\
    --api-base http://127.0.0.1:3004/v1 \\
    --allowlist models.allowlist.real.json \\
    --port 8793 \\
    --api-token "$FREE_LLM_API_TOKEN"

  python3 voice_router_mvp.py --selftest
"""
from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import os
import signal
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# ─── Config ───────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ALLOWLIST_PATH = os.path.join(SCRIPT_DIR, "models.allowlist.real.json")
DECISION_LOG_PATH = os.path.join(SCRIPT_DIR, "router_decisions_voice.jsonl")
log_lock = threading.Lock()

# Per-attempt timeout. Voice needs speed — don't let one slow model hold the request.
ATTEMPT_TIMEOUT = 12.0
# How long to try the preferred model before falling back to the parallel race.
PREFERRED_TIMEOUT = 8.0


# ─── Model capabilities (mirrors freellm_router_mvp.py structure) ─────────────

class ModelCapability:
    __slots__ = ("model", "claude_code_compatible", "supports_tools",
                 "supports_streaming", "context_window", "roles", "notes")

    def __init__(self, model: str, claude_code_compatible: bool, supports_tools: bool,
                 supports_streaming: bool, context_window: int, roles: list[str], notes: str = ""):
        self.model = model
        self.claude_code_compatible = claude_code_compatible
        self.supports_tools = supports_tools
        self.supports_streaming = supports_streaming
        self.context_window = context_window
        self.roles = roles
        self.notes = notes


def load_allowlist(path: str) -> list[ModelCapability]:
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    out = []
    for item in raw.get("models", []):
        out.append(ModelCapability(
            model=item["model"],
            claude_code_compatible=bool(item.get("claudeCodeCompatible")),
            supports_tools=bool(item.get("supportsTools")),
            supports_streaming=bool(item.get("supportsStreaming", True)),
            context_window=int(item.get("contextWindow", 8192)),
            roles=list(item.get("roles", [])),
            notes=item.get("notes", ""),
        ))
    return out


# ─── Speed-first policy ordering ──────────────────────────────────────────────
# KEY DIFFERENCE from the Claude Code router: FAST models first, strong models
# only when explicitly needed. The voice agent dies on latency.

VOICE_POLICIES = {
    # Most voice requests carry tools (phone/CRM/search). Pick the FASTEST tool-capable model.
    "tools": [
        "llama-3.3-70b",        # fast + tool-capable
        "gpt-oss-20b",           # fast + tool-capable fallback
        "gpt-4.1",               # mid + tool-capable
        "mistral-large-3-675b",  # slow but strong — last resort for tools
    ],
    # Plain short chat — fastest model.
    "fast": [
        "gpt-oss-20b",
        "llama-3.3-70b",
        "gpt-4.1",
    ],
    # Explicit reasoning/analysis/strategy — accept the latency for quality.
    "reasoning": [
        "mistral-large-3-675b",  # smart, slower
        "gpt-4.1",               # mid fallback
        "llama-3.3-70b",         # fast fallback
    ],
    # Long context — need the big context window.
    "long-context": [
        "nemotron-3-super-120b",  # 1M ctx
        "mistral-large-3-675b",   # 131k ctx
        "gpt-4.1",                # 128k ctx
    ],
    # Summarization — mid-tier is fine, don't need the strongest.
    "summarization": [
        "gpt-4.1",
        "mistral-large-3-675b",
        "llama-3.3-70b",
    ],
}


# ─── Token estimation + request inspection ──────────────────────────────────

def estimate_tokens(request: dict[str, Any]) -> int:
    if not isinstance(request, dict):
        return 0
    total = 0
    for msg in request.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += len(str(part.get("text", "")))
    return max(1, total // 4)


def extract_text(request: dict[str, Any]) -> str:
    parts = []
    for msg in request.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for p in content:
                if isinstance(p, dict) and p.get("text"):
                    parts.append(p["text"])
    return " ".join(parts).lower()


def has_any_word(text: str, words: list[str]) -> bool:
    for word in words:
        if " " in word:
            if word in text:
                return True
        else:
            import re
            if re.search(r'\b' + re.escape(word) + r'\b', text):
                return True
    return False


def classify_voice_policy(request: dict[str, Any]) -> str:
    """Speed-first classification for voice traffic."""
    tokens = estimate_tokens(request)
    text = extract_text(request)
    has_tools = bool(request.get("tools") or request.get("tool_choice"))

    # Long context always wins — need the big window.
    if tokens > 60000:
        return "long-context"
    # Explicit reasoning — escalate to the smart (slow) model.
    if has_any_word(text, [
        "analyze", "analyse", "strategy", "architect", "compare", "tradeoff",
        "pros and cons", "synthesize", "reason", "prove", "derive",
        "design pattern", "optimization", "algorithm", "complexity",
    ]):
        return "reasoning"
    # Summarization.
    if has_any_word(text, ["summarize", "summary", "tl;dr", "overview"]):
        return "summarization"
    # Tools present → speed-first tool model.
    if has_tools:
        return "tools"
    # Short plain chat → fastest.
    if tokens < 2000:
        return "fast"
    return "fast"


def eligible_models(request: dict[str, Any], capabilities: list[ModelCapability]) -> list[ModelCapability]:
    needs_tools = bool(request.get("tools") or request.get("tool_choice"))
    tokens = estimate_tokens(request)
    return [
        cap for cap in capabilities
        if cap.claude_code_compatible
        and cap.context_window >= tokens
        and (not needs_tools or cap.supports_tools)
    ]


def ordered_candidates(request: dict[str, Any], capabilities: list[ModelCapability]) -> list[ModelCapability]:
    """Return models in speed-first preference order for the request's policy."""
    eligible = eligible_models(request, capabilities)
    by_name = {cap.model: cap for cap in eligible}
    policy = classify_voice_policy(request)
    ordered: list[ModelCapability] = []
    seen: set[str] = set()
    for name in VOICE_POLICIES.get(policy, []):
        cap = by_name.get(name)
        if cap and cap.model not in seen:
            ordered.append(cap)
            seen.add(cap.model)
    # Append any remaining eligible as final fallbacks.
    for cap in eligible:
        if cap.model not in seen:
            ordered.append(cap)
            seen.add(cap.model)
    return ordered


# ─── Error classification (shared logic with Claude Code router) ────────────

_NONRETRYABLE_SUBSTRINGS = (
    "401", "authentication", "invalid api key", "invalid_api_key",
    "unauthorized", "forbidden", "403", "model_not_found", "not in the catalog",
    "400", "invalid_request", "bad request",
)
_RATELIMIT_SUBSTRINGS = (
    "429", "rate limit", "exhausted", "too many requests", "rate_limit",
)


def classify_upstream_error(exc_str: str) -> str:
    low = (exc_str or "").lower()
    if any(kw in low for kw in _RATELIMIT_SUBSTRINGS):
        return "rate_limit"
    if any(kw in low for kw in _NONRETRYABLE_SUBSTRINGS):
        return "nonretryable"
    return "transient"


# ─── HTTP helpers ────────────────────────────────────────────────────────────

def http_json(method: str, url: str, payload: dict[str, Any] | None = None,
              auth_token: str | None = None, timeout: float = ATTEMPT_TIMEOUT) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    headers = {"content-type": "application/json"}
    if auth_token:
        headers["authorization"] = f"Bearer {auth_token}"
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parsed.netloc, timeout=timeout)
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
    if endpoint.startswith("/v1/"):
        return base + endpoint
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return base + "/v1" + endpoint if "/v1" not in base else base + endpoint


# ─── Storm-hardened fallback (preference-ordered, like Claude Code router) ───

def _attempt_one_model(model: str, payload: dict[str, Any], api_base: str,
                       api_token: str | None, timeout: float = ATTEMPT_TIMEOUT) -> tuple[str, dict[str, Any] | None, str | None]:
    try:
        response = http_json("POST", join_v1_url(api_base, "/chat/completions"),
                             payload, api_token, timeout=timeout)
        return model, response, None
    except Exception as exc:
        return model, None, classify_upstream_error(str(exc))


def race_for_first_success(payload_template: dict[str, Any], candidates: list[str],
                           api_base: str, api_token: str | None) -> tuple[dict[str, Any], str, str]:
    """Try preferred model first; on failure race the rest in parallel."""
    if not candidates:
        raise RuntimeError("No compatible models available for this voice request.")

    failures: list[str] = []

    # Step 1: preferred (fastest) model, alone, tight timeout.
    preferred = candidates[0]
    payload = dict(payload_template)
    payload["model"] = preferred
    model, response, err_kind = _attempt_one_model(preferred, payload, api_base, api_token, timeout=PREFERRED_TIMEOUT)
    if response is not None:
        return response, model, ""
    failures.append(f"{preferred}: {err_kind}")

    # Step 2: race remaining in parallel.
    rest = candidates[1:]

    def run_pass(alive: list[str]) -> tuple[dict[str, Any], str, list[str]] | None:
        local_failures: list[str] = []
        if len(alive) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(alive))) as ex:
                futures = {}
                for m in alive:
                    p = dict(payload_template)
                    p["model"] = m
                    futures[ex.submit(_attempt_one_model, m, p, api_base, api_token)] = m
                for fut in concurrent.futures.as_completed(futures):
                    model, response, err_kind = fut.result()
                    if response is not None:
                        return response, model, local_failures
                    local_failures.append(f"{model}: {err_kind}")
        else:
            for m in alive:
                p = dict(payload_template)
                p["model"] = m
                model, response, err_kind = _attempt_one_model(m, p, api_base, api_token)
                if response is not None:
                    return response, model, local_failures
                local_failures.append(f"{model}: {err_kind}")
        return None

    if rest:
        result = run_pass(rest)
        if result is not None:
            response, winner, local_failures = result
            failures.extend(local_failures)
            return response, winner, "; ".join(failures)

        # Step 3: one short global backoff if all rate-limited, then retry.
        if all("rate_limit" in f for f in failures):
            time.sleep(2.0)
            result = run_pass(rest)
            if result is not None:
                response, winner, local_failures = result
                failures.extend(local_failures)
                return response, winner, "; ".join(failures)

    raise RuntimeError("All compatible models failed: " + " | ".join(failures))


# ─── Streaming pass-through ──────────────────────────────────────────────────

def stream_passthrough(payload_template: dict[str, Any], candidates: list[str],
                       api_base: str, api_token: str | None,
                       handler: BaseHTTPRequestHandler) -> tuple[str, str]:
    """Stream OpenAI SSE from the first model that responds 200, straight through."""
    failures: list[str] = []
    parsed = urllib.parse.urlparse(api_base)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    base_path = parsed.path.rstrip("/")
    target_path = base_path + "/chat/completions"
    if "/v1" not in target_path:
        target_path = base_path + "/v1/chat/completions"
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    for model in candidates:
        payload = dict(payload_template)
        payload["model"] = model
        payload["stream"] = True
        headers = {"content-type": "application/json", "accept": "text/event-stream"}
        if api_token:
            headers["authorization"] = f"Bearer {api_token}"
        try:
            conn = conn_cls(host, port, timeout=15)
            conn.request("POST", target_path, body=json.dumps(payload).encode("utf-8"), headers=headers)
            response = conn.getresponse()
            if response.status != 200:
                body = response.read()
                conn.close()
                failures.append(f"{model}: {classify_upstream_error(f'HTTP {response.status}: {body}')}")
                continue
            # Commit headers + pipe the SSE stream straight through.
            handler.send_response(200)
            handler.send_header("content-type", "text/event-stream")
            handler.send_header("cache-control", "no-cache")
            handler.send_header("connection", "close")
            handler.end_headers()
            handler.close_connection = True
            while True:
                chunk = response.read(4096)
                if not chunk:
                    break
                try:
                    handler.wfile.write(chunk)
                    handler.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
            conn.close()
            return model, "; ".join(failures)
        except Exception as exc:
            failures.append(f"{model}: {classify_upstream_error(str(exc))}")
            try:
                conn.close()
            except Exception:
                pass
            continue
    raise RuntimeError("All compatible models failed for streaming: " + " | ".join(failures))


# ─── Decision logging ────────────────────────────────────────────────────────

def log_decision(entry: dict[str, Any]) -> None:
    entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with log_lock:
            with open(DECISION_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ─── Dashboard (minimal, reuses the same JSON API shape) ─────────────────────

DASHBOARD_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Voice Router — Rachel</title><meta http-equiv="refresh" content="5">
<style>body{font-family:system-ui;background:#0b0f19;color:#f3f4f6;margin:2rem}
.card{background:rgba(22,28,45,.6);border:1px solid rgba(255,255,255,.08);
border-radius:12px;padding:1.5rem;margin-bottom:1rem}
h1{font-size:1.2rem} .stat{font-size:2rem;font-weight:700}
.muted{color:#9ca3af;font-size:.8rem;text-transform:uppercase;letter-spacing:.5px}
.ok{color:#10b981} .err{color:#ef4444} pre{white-space:pre-wrap;font-size:.75rem}
</style></head><body><h1>🎙️ Voice Router (Rachel) — Speed-First</h1>
<div class="card"><div class="muted">Last 50 requests</div>
<div id="stats" class="stat">loading…</div></div>
<div class="card"><div class="muted">Recent decisions</div><pre id="decisions"></pre></div>
<script>
fetch('/api/decisions').then(r=>r.json()).then(d=>{
  const decs=d.decisions||[];const n=decs.length;
  const s=decs.filter(x=>x.status==='success').length;
  const lats=decs.map(x=>x.latency_ms||0);
  const avg=lats.length?Math.round(lats.reduce((a,b)=>a+b,0)/lats.length):0;
  document.getElementById('stats').innerHTML=
    `<span class="ok">${s}/${n}</span> success (${n?Math.round(s/n*100):0}%) · avg ${avg}ms`;
  document.getElementById('decisions').textContent=
    decs.slice(-15).reverse().map(x=>`${x.timestamp} ${x.status==='success'?'✅':'❌'} ${x.policy||''} ${x.selected_model||''} ${x.latency_ms||0}ms`).join('\\n');
});
</script></body></html>"""


# ─── HTTP server ─────────────────────────────────────────────────────────────

class VoiceRouterHandler(BaseHTTPRequestHandler):
    server_version = "VoiceRouter/0.1"
    api_base = "http://127.0.0.1:3004/v1"
    api_token: str | None = None
    allowlist_path = DEFAULT_ALLOWLIST_PATH

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # quiet

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/health"):
            write_json(self, 200, {"ok": True, "router": "voice", "mode": "speed-first"})
            return
        if path == "/dashboard":
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
            return
        if path == "/api/decisions":
            decisions = []
            try:
                with log_lock:
                    if os.path.exists(DECISION_LOG_PATH):
                        with open(DECISION_LOG_PATH, "r", encoding="utf-8") as f:
                            for line in f.readlines()[-50:]:
                                try:
                                    decisions.append(json.loads(line))
                                except Exception:
                                    pass
            except Exception:
                pass
            write_json(self, 200, {"decisions": decisions})
            return
        write_json(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        # OpenAI-compatible endpoints the voice agent uses.
        if path not in ("/v1/chat/completions", "/v1/chat/completions/"):
            write_json(self, 404, {"error": "not found"})
            return

        start_time = time.time()
        request: dict[str, Any] = {}
        try:
            request = read_json_body(self)
            capabilities = load_allowlist(self.allowlist_path)
            candidates = ordered_candidates(request, capabilities)
            if not candidates:
                raise RuntimeError("No eligible models for this request.")
            candidate_names = [c.model for c in candidates]
            policy = classify_voice_policy(request)
            wants_stream = bool(request.get("stream"))

            if wants_stream:
                final_model, fallback_notes = stream_passthrough(
                    request, candidate_names, self.api_base, self.api_token, self
                )
                latency_ms = int((time.time() - start_time) * 1000)
                log_decision({
                    "policy": policy, "selected_model": final_model,
                    "fallback_notes": fallback_notes, "streamed": True,
                    "input_tokens": estimate_tokens(request),
                    "latency_ms": latency_ms, "status": "success",
                })
                return

            # Non-streaming: race for first success.
            response, final_model, fallback_notes = race_for_first_success(
                request, candidate_names, self.api_base, self.api_token
            )
            latency_ms = int((time.time() - start_time) * 1000)
            log_decision({
                "policy": policy, "selected_model": final_model,
                "fallback_notes": fallback_notes,
                "input_tokens": estimate_tokens(request),
                "output_tokens": (response.get("usage") or {}).get("completion_tokens", 0),
                "latency_ms": latency_ms, "status": "success",
            })
            write_json(self, 200, response, headers={
                "x-router-selected-model": final_model,
                "x-router-policy": policy,
                "x-router-fallbacks": fallback_notes[:800],
            })
        except Exception as exc:
            latency_ms = int((time.time() - start_time) * 1000)
            log_decision({
                "policy": classify_voice_policy(request) if request else "unknown",
                "input_tokens": estimate_tokens(request) if request else 0,
                "latency_ms": latency_ms, "status": "error",
                "error_message": str(exc),
            })
            write_json(self, 502, {"error": {"message": str(exc), "type": "router_error"}})


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length", 0) or 0)
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def write_json(handler: BaseHTTPRequestHandler, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
    data = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(data)))
    for k, v in (headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    try:
        handler.wfile.write(data)
    except (BrokenPipeError, ConnectionResetError):
        pass


# ─── Entry points ────────────────────────────────────────────────────────────

def run_proxy(api_base: str, api_token: str | None, allowlist_path: str, host: str, port: int) -> None:
    VoiceRouterHandler.api_base = api_base
    VoiceRouterHandler.api_token = api_token
    VoiceRouterHandler.allowlist_path = allowlist_path
    server = ThreadingHTTPServer((host, port), VoiceRouterHandler)

    def stop(_s: int, _f: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f"🎙️  Voice Router (speed-first) listening on http://{host}:{port}")
    print(f"    Upstream: {api_base}")
    print(f"    Allowlist: {allowlist_path}")
    print(f"    Dashboard: http://{host}:{port}/dashboard")
    print(f"    Point the voice agent at: API_URL='http://{host}:{port}/v1/chat/completions'")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


def selftest() -> int:
    """Verify allowlist loads + policy classification."""
    print("=== Voice Router self-test ===")
    caps = load_allowlist(DEFAULT_ALLOWLIST_PATH)
    print(f"Loaded {len(caps)} models from allowlist.")
    for c in caps:
        print(f"  {c.model:30s} tools={c.supports_tools} ctx={c.context_window:>8} roles={c.roles}")
    print()
    cases = [
        ("tool-bearing request", {"messages": [{"role": "user", "content": "Call mom"}], "tools": [{"type": "function", "function": {"name": "x"}}]}),
        ("plain chat", {"messages": [{"role": "user", "content": "Hi"}]}),
        ("reasoning", {"messages": [{"role": "user", "content": "Compare the tradeoffs of microservices vs monolith."}]}),
        ("long context", {"messages": [{"role": "user", "content": "x " * 30000}]}),
    ]
    for label, req in cases:
        policy = classify_voice_policy(req)
        ordered = [c.model for c in ordered_candidates(req, caps)]
        print(f"  {label:22s} -> policy={policy:14s} order={ordered}")
    print("\n✅ Self-test passed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Voice Router — speed-first OpenAI-format router for the Thrivbe Voice Agent.")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("selftest", help="Run self-test")
    p = sub.add_parser("proxy", help="Run the proxy server")
    p.add_argument("--api-base", default=os.environ.get("FREE_LLM_API_BASE", "http://127.0.0.1:3004/v1"))
    p.add_argument("--api-token", default=os.environ.get("FREE_LLM_API_TOKEN"))
    p.add_argument("--allowlist", default=DEFAULT_ALLOWLIST_PATH)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("VOICE_ROUTER_PORT", "8793")))
    args = ap.parse_args()

    if args.cmd == "selftest":
        return selftest()
    if args.cmd == "proxy" or args.cmd is None:
        run_proxy(args.api_base, args.api_token, args.allowlist, args.host, args.port)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
