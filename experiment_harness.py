#!/usr/bin/env python3
"""
Experiment harness for the FreeLLM Claude Router v4 (meta-router).

Drives mixed, realistic traffic sequentially (matching the autoresearch loop's
tight sequential cadence that triggers upstream rate-limit buildup) through
http://127.0.0.1:8792/v1/messages, then reports success-rate and average
latency over the LAST N requests — the exact metric the dashboard shows
(/api/decisions returns readlines()[-50:]).

Usage:
    python3 experiment_harness.py --requests 50
    python3 experiment_harness.py --requests 50 --port 8792 --gap 0.5
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error

ROUTER = "http://127.0.0.1:{port}"

# A compact tool schema (Claude Code always sends tools, even for simple prompts).
PING_TOOL = {
    "name": "ping",
    "description": "Echo a value back.",
    "input_schema": {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    },
}

# A medium context block (~5k tokens) to resemble real Claude Code startup payload.
MED_CTX = ("You are a senior engineer reviewing a pull request. Consider style, "
           "correctness, and edge cases. Context: ") + ("lorem ipsum dolor sit amet. " * 120)


def make_request(kind: str) -> dict:
    if kind == "simple":
        return {
            "model": "gpt-oss-120b",
            "max_tokens": 40,
            "messages": [{"role": "user", "content": "Say ROUTER_OK and nothing else."}],
        }
    if kind == "tools":
        return {
            "model": "gpt-oss-120b",
            "max_tokens": 120,
            "messages": [{"role": "user", "content": MED_CTX + "\n\nReply with a one-line summary."}],
            "tools": [PING_TOOL],
        }
    if kind == "compare":
        return {
            "model": "gpt-oss-120b",
            "max_tokens": 160,
            "messages": [{"role": "user", "content": "Compare the pros and cons of REST vs GraphQL, briefly."}],
        }
    raise ValueError(kind)


def post(port: int, payload: dict, timeout: float = 60.0) -> tuple[int, dict | str, float]:
    url = f"{ROUTER.format(port=port)}/v1/messages"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"content-type": "application/json"}, method="POST"
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            elapsed = time.monotonic() - t0
            try:
                return resp.status, json.loads(raw.decode("utf-8")), elapsed
            except Exception:
                return resp.status, raw[:200].decode("utf-8", "replace"), elapsed
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - t0
        try:
            return e.code, json.loads(e.read().decode("utf-8")), elapsed
        except Exception:
            return e.code, f"HTTP {e.code}", elapsed
    except Exception as e:
        elapsed = time.monotonic() - t0
        return 0, str(e)[:200], elapsed


def fetch_decisions(port: int) -> list[dict]:
    url = f"{ROUTER.format(port=port)}/api/decisions"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("decisions", [])
    except Exception as e:
        print(f"[harness] could not fetch /api/decisions: {e}", file=sys.stderr)
        return []


def summarize(decisions: list[dict], label: str) -> None:
    if not decisions:
        print(f"\n[{label}] no decisions available")
        return
    n = len(decisions)
    succ = sum(1 for d in decisions if d.get("status") == "success")
    lats = [d.get("latency_ms", 0) for d in decisions if d.get("latency_ms") is not None]
    avg = (sum(lats) / len(lats) / 1000.0) if lats else 0.0
    err_kinds: dict[str, int] = {}
    for d in decisions:
        if d.get("status") != "success":
            e = (d.get("error_message") or "").lower()
            if "429" in e or "exhausted" in e or "rate_limit" in e:
                err_kinds["429"] = err_kinds.get("429", 0) + 1
            elif "401" in e or "authentication" in e or "invalid api key" in e:
                err_kinds["401"] = err_kinds.get("401", 0) + 1
            elif "broken pipe" in e:
                err_kinds["broken-pipe"] = err_kinds.get("broken-pipe", 0) + 1
            elif "timed out" in e or "timeout" in e:
                err_kinds["timeout"] = err_kinds.get("timeout", 0) + 1
            else:
                err_kinds["other"] = err_kinds.get("other", 0) + 1
    print(f"\n[{label}] over {n} decisions: "
          f"success={succ}/{n} ({succ/n*100:.1f}%)  "
          f"avg_latency={avg:.2f}s  "
          f"errors={err_kinds}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--requests", type=int, default=50)
    ap.add_argument("--gap", type=float, default=0.4, help="seconds between requests")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    # Mixed cadence resembling the autoresearch loop: mostly tool-bearing coding
    # requests (-> v2), some compare/synthesis (-> v3), a few simple (-> v1).
    kinds = (
        ["tools"] * 3 + ["compare"] + ["simple"]
    )  # 60% tools, 20% compare, 20% simple

    decisions_before = fetch_decisions(args.port)
    summarize(decisions_before[-50:], "BEFORE (dashboard last-50)")

    print(f"\nDriving {args.requests} mixed requests through "
          f"http://127.0.0.1:{args.port}/v1/messages (gap={args.gaps}s)...\n"
          if False else
          f"\nDriving {args.requests} mixed requests through "
          f"http://127.0.0.1:{args.port}/v1/messages (gap={args.gap}s)...\n")

    results = []
    for i in range(args.requests):
        kind = kinds[i % len(kinds)]
        payload = make_request(kind)
        code, body, elapsed = post(args.port, payload, timeout=args.timeout)
        ok = code == 200 and isinstance(body, dict) and "content" in body
        results.append((kind, code, ok, elapsed))
        tag = "OK " if ok else "ERR"
        snippet = ""
        if not ok and isinstance(body, dict):
            snippet = str(body.get("error") or body.get("type") or "")[:80]
        elif not ok:
            snippet = str(body)[:80]
        print(f"  [{i+1:02d}/{args.requests}] {tag} {kind:7s} "
              f"http={code} t={elapsed:5.2f}s {snippet}")
        if args.gap:
            time.sleep(args.gap)

    # Summary of THIS run
    run_ok = sum(1 for _, _, ok, _ in results if ok)
    run_lats = [e for _, _, ok, e in results if ok]
    avg_run = (sum(run_lats) / len(run_lats)) if run_lats else 0.0
    print(f"\n[harness run] success={run_ok}/{args.requests} "
          f"({run_ok/args.requests*100:.1f}%)  "
          f"avg_latency(success)={avg_run:.2f}s")

    # Dashboard metric after the run
    time.sleep(0.5)
    decisions_after = fetch_decisions(args.port)
    summarize(decisions_after[-50:], "AFTER  (dashboard last-50)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
