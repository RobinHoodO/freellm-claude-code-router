#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

ROUTER_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_FILE = os.path.join(ROUTER_DIR, "freellm_router_mvp.py")
PORT = 8791

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

def send_post(payload: dict) -> tuple[int, dict, dict, float]:
    url = f"http://127.0.0.1:{PORT}/v1/messages"
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=45) as res:
            res_headers = {k.lower(): v for k, v in res.getheaders()}
            body = json.loads(res.read().decode("utf-8"))
            return res.status, body, res_headers, time.time() - start
    except urllib.error.HTTPError as err:
        try:
            body = json.loads(err.read().decode("utf-8"))
        except:
            body = {"error": err.reason}
        return err.code, body, {k.lower(): v for k, v in err.headers.items()}, time.time() - start
    except Exception as err:
        return 500, {"error": str(err)}, {}, time.time() - start

def restart_v2():
    print("[Optimizer] Restarting V2 Proxy server...")
    subprocess.run("ps aux | grep freellm_router_mvp.py | grep -v grep | awk '{print $2}' | xargs kill -9 || true", shell=True)
    subprocess.run("claude-router --mode v2 --start-proxy", shell=True)
    time.sleep(2)

def get_current_policies() -> dict:
    with open(PROXY_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r"V2_POLICIES = (\{.*?\})", content, re.DOTALL)
    if not match:
        raise RuntimeError("Could not find V2_POLICIES dict in proxy file")
    dict_str = match.group(1)
    return eval(dict_str)

def write_policies(policies: dict):
    with open(PROXY_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    
    formatted_lines = ["V2_POLICIES = {"]
    for policy, models in policies.items():
        formatted_lines.append(f'    "{policy}": [')
        for model in models:
            formatted_lines.append(f'        "{model}",')
        formatted_lines.append("    ],")
    formatted_lines.append("}")
    formatted_block = "\n".join(formatted_lines)
    
    new_content = re.sub(r"V2_POLICIES = \{.*?\}", formatted_block, content, flags=re.DOTALL)
    with open(PROXY_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"[Optimizer] Updated V2_POLICIES in {PROXY_FILE}")

def run_evaluation() -> tuple[float, list[dict]]:
    results = []
    successes = 0
    for scenario in SCENARIOS:
        print(f"  Testing {scenario['name']}...")
        status, body, headers, latency = send_post(scenario["payload"])
        time.sleep(0.5)
        
        success = (status == 200)
        if success:
            successes += 1
            
        results.append({
            "scenario": scenario["name"],
            "status": status,
            "latency": latency,
            "fallback_notes": headers.get("x-router-fallbacks", ""),
            "selected_model": headers.get("x-router-selected-model", ""),
            "policy": headers.get("x-router-policy", "")
        })
    success_rate = (successes / len(SCENARIOS)) * 100
    return success_rate, results

def main():
    print("=== FreeLLM Claude Router Auto-Optimizer ===")
    
    policies = get_current_policies()
    print(f"Initial V2 Policies: {policies}")
    
    iteration = 1
    max_iterations = 10
    
    while iteration <= max_iterations:
        print(f"\n--- Iteration {iteration} ---")
        restart_v2()
        
        success_rate, results = run_evaluation()
        print(f"Success Rate: {success_rate}%. Results:")
        
        failures_by_policy = {}
        for res in results:
            print(f"  {res['scenario']}: Status={res['status']}, Latency={res['latency']:.2f}s, Selected={res['selected_model']}")
            
            notes = res["fallback_notes"]
            policy = res["policy"]
            if policy.startswith("ensemble:"):
                policy = policy[9:]
            
            if notes:
                print(f"    Fallbacks occurred: {notes}")
                failed_models = re.findall(r"([\w\-/:.:]+) \(attempt \d+\):", notes)
                if failed_models:
                    if policy not in failures_by_policy:
                        failures_by_policy[policy] = []
                    failures_by_policy[policy].extend(failed_models)
        
        total_fallbacks = sum(1 for res in results if res["fallback_notes"])
        avg_latency = sum(res["latency"] for res in results) / len(results)
        
        print(f"Iteration summary: Success Rate={success_rate}%, Total Fallbacks={total_fallbacks}, Avg Latency={avg_latency:.2f}s")
        
        if success_rate >= 95.0 and total_fallbacks == 0:
            print("\n[Optimizer] SUCCESS: Reached target criteria (>=95% success rate and 0 fallback delays)!")
            print(f"Optimal V2 Policies: {policies}")
            break
            
        if not failures_by_policy:
            print("[Optimizer] No specific model failures parsed from headers. Stopping optimization.")
            break
            
        modified = False
        for policy, failed_list in failures_by_policy.items():
            if policy not in policies:
                continue
            model_list = list(policies[policy])
            unique_failures = list(dict.fromkeys(failed_list))
            
            for failed_model in unique_failures:
                if failed_model in model_list:
                    print(f"  [Action] Moving failed model '{failed_model}' to the end of policy '{policy}'")
                    model_list.remove(failed_model)
                    model_list.append(failed_model)
                    modified = True
            policies[policy] = model_list
            
        if not modified:
            print("[Optimizer] No policies were changed this round. Stopping.")
            break
            
        write_policies(policies)
        iteration += 1

    print("\n=== Optimization Complete ===")

if __name__ == "__main__":
    main()
