#!/usr/bin/env python3
"""
Reliability Benchmark Experiment for FreeLLM Claude Router.
Runs multiple test scenarios on all 4 versions, measures latency and success rates,
captures fallback behaviors from proxy headers, and writes a detailed markdown report.
"""

import json
import os
import urllib.request
import urllib.error
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH = os.path.join(SCRIPT_DIR, "reliability_experiment_report.md")

PORTS = {
    "v1 (Single Model)": 8787,
    "v2 (Task-Aware)": 8791,
    "v3 (Ensemble)": 8789,
    "v4 (Meta-Router)": 8792
}

# Generate a simulated large context (approx 2,000 tokens)
large_context_text = "This is a context block repeated to simulate a large prompt. " * 300

SCENARIOS = [
    {
        "name": "Simple Chat",
        "payload": {
            "model": "qwen/qwen3-coder:free",
            "max_tokens": 30,
            "messages": [{"role": "user", "content": "Say hello in exactly three words."}]
        }
    },
    {
        "name": "Coding Task",
        "payload": {
            "model": "qwen/qwen3-coder:free",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Write a python function that prints the first N numbers of the Fibonacci sequence."}]
        }
    },
    {
        "name": "Comparison/Synthesis",
        "payload": {
            "model": "qwen/qwen3-coder:free",
            "max_tokens": 160,
            "messages": [{"role": "user", "content": "Compare the pros and cons of REST and GraphQL APIs."}]
        }
    },
    {
        "name": "Tool Use",
        "payload": {
            "model": "qwen/qwen3-coder:free",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "Use tool ping with value ok."}],
            "tools": [
                {
                    "name": "ping",
                    "description": "Ping tool",
                    "input_schema": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"]
                    }
                }
            ]
        }
    },
    {
        "name": "Large Context",
        "payload": {
            "model": "qwen/qwen3-coder:free",
            "max_tokens": 100,
            "messages": [
                {"role": "user", "content": f"Here is the context: {large_context_text}\nSummarize the purpose of the context in one short sentence."}
            ]
        }
    }
]

def send_post(port: int, payload: dict) -> tuple[int, dict, dict, float]:
    url = f"http://127.0.0.1:{port}/v1/messages"
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=45) as res:
            res_headers = {k.lower(): v for k, v in res.getheaders()}
            body = json.loads(res.read().decode("utf-8"))
            latency = time.time() - start
            return res.status, body, res_headers, latency
    except urllib.error.HTTPError as err:
        try:
            body = json.loads(err.read().decode("utf-8"))
        except Exception:
            body = {"error": err.reason}
        latency = time.time() - start
        return err.code, body, {k.lower(): v for k, v in err.headers.items()}, latency
    except Exception as err:
        latency = time.time() - start
        return 500, {"error": str(err)}, {}, latency

def check_port(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0

def run_benchmarks() -> dict:
    results = {}
    iterations = 2  # Run each prompt twice to capture statistics and transient 429 errors

    for version_name, port in PORTS.items():
        print(f"\nBenchmarking {version_name} on port {port}...")
        results[version_name] = []
        if not check_port(port):
            print(f"  Warning: Proxy is not running on port {port}. Skipping.")
            continue

        for i in range(iterations):
            print(f"  Iteration {i+1}/{iterations}...")
            for idx, scenario in enumerate(SCENARIOS):
                print(f"    Running scenario: {scenario['name']}...")
                status, body, headers, latency = send_post(port, scenario["payload"])
                
                # Check for fallbacks or retries recorded in header
                fallback_str = headers.get("x-router-fallbacks", "")
                had_fallback = bool(fallback_str)
                selected_model = headers.get("x-router-selected-model", "")
                selected_version = headers.get("x-router-selected-version", "")
                policy = headers.get("x-router-policy", "")
                reason = headers.get("x-router-route-reason", "")

                results[version_name].append({
                    "scenario": scenario["name"],
                    "status": status,
                    "latency": latency,
                    "had_fallback": had_fallback,
                    "fallback_notes": fallback_str,
                    "selected_model": selected_model,
                    "selected_version": selected_version,
                    "policy": policy,
                    "route_reason": reason,
                    "error": body.get("error", None) if status != 200 else None
                })
                # Prevent slamming free-tier endpoints too fast
                time.sleep(1)

    return results

def generate_report(results: dict) -> None:
    print(f"\nGenerating report at {REPORT_PATH}...")
    
    md_lines = [
        "# FreeLLM Claude Router: Reliability Experiment Report",
        f"Generated on: {time.strftime('%Y-%m-%d %H:%M:%S Local Time')}",
        "",
        "This benchmark compares the reliability, latency, and recovery capabilities of the four router variants (v1, v2, v3, v4) using your self-hosted FreeLLMAPI instance.",
        "",
        "## Executive Summary",
        ""
    ]

    # Summary table columns
    table_headers = ["Variant", "Total Requests", "Successes", "Success Rate", "Avg Latency (s)", "Fallbacks Triggered"]
    table_rows = []

    variant_summaries = {}
    for variant, runs in results.items():
        if not runs:
            continue
        total = len(runs)
        successes = sum(1 for r in runs if r["status"] == 200)
        rate = (successes / total) * 100 if total > 0 else 0
        avg_latency = sum(r["latency"] for r in runs) / total if total > 0 else 0
        fallbacks = sum(1 for r in runs if r["had_fallback"])
        
        table_rows.append([
            variant,
            str(total),
            str(successes),
            f"{rate:.1f}%",
            f"{avg_latency:.2f}s",
            str(fallbacks)
        ])
        variant_summaries[variant] = {
            "rate": rate,
            "latency": avg_latency,
            "fallbacks": fallbacks,
            "runs": runs
        }

    # Add summary markdown table
    md_lines.append("| " + " | ".join(table_headers) + " |")
    md_lines.append("| " + " | ".join(["---"] * len(table_headers)) + " |")
    for row in table_rows:
        md_lines.append("| " + " | ".join(row) + " |")
    md_lines.append("")

    # Reliability evaluation
    md_lines.append("## Reliability Evaluation")
    md_lines.append("")
    
    # Analyze best version
    best_rate = -1
    best_variant = None
    for var, summary in variant_summaries.items():
        if summary["rate"] > best_rate:
            best_rate = summary["rate"]
            best_variant = var
        elif summary["rate"] == best_rate and best_variant:
            # Tie breaker: choose the one with lower latency
            if summary["latency"] < variant_summaries[best_variant]["latency"]:
                best_variant = var

    md_lines.append(f"> **Verdict**: **{best_variant}** proved to be the most reliable option during this benchmark run, achieving a **{variant_summaries[best_variant]['rate']:.1f}%** success rate.")
    md_lines.append("")
    md_lines.append("### Key Insights:")
    md_lines.append("- **Version 1 (Baseline)** is fast but vulnerable to transient API provider rate limits (429s) or model failures because it makes a single static request.")
    md_lines.append("- **Version 2 (Task-Aware)** improves reliability significantly by retrying alternate compatible models in the policy pool when the first model fails.")
    md_lines.append("- **Version 3 (Ensemble)** has higher latency due to parallel advisor calls and synthesis steps. If advisors fail, it falls back to single-model execution.")
    md_lines.append("- **Version 4 (Meta-Router)** routes dynamically. It balances speed for simple tasks (v1), robustness for coding/tools (v2), and multi-perspective synthesis for strategy (v3).")
    md_lines.append("")

    # Detailed logs per version
    md_lines.append("## Detailed Scenario Runs")
    md_lines.append("")

    for variant, summary in variant_summaries.items():
        md_lines.append(f"### {variant}")
        md_lines.append("| Scenario | Status | Latency | Policy / Selected Model | Fallback? | Notes |")
        md_lines.append("| --- | --- | --- | --- | --- | --- |")
        for run in summary["runs"]:
            status_emoji = "✅" if run["status"] == 200 else "❌"
            fallback_emoji = "⚠️ Yes" if run["had_fallback"] else "No"
            model_info = f"`{run['policy']}` → `{run['selected_model']}`" if run["policy"] else f"`{run['selected_model']}`"
            notes = run["fallback_notes"] if run["had_fallback"] else ""
            if run["error"]:
                notes = f"Error: {run['error']}"
            md_lines.append(f"| {run['scenario']} | {status_emoji} ({run['status']}) | {run['latency']:.2f}s | {model_info} | {fallback_emoji} | {notes} |")
        md_lines.append("")

    # Write report
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

def main() -> None:
    print("Starting FreeLLM Claude Router Reliability Benchmark...")
    results = run_benchmarks()
    generate_report(results)
    print("\nBenchmark complete!")

if __name__ == "__main__":
    main()
