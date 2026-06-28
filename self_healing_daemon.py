#!/usr/bin/env python3
"""
FreeLLM Claude Router Self-Healing Daemon.
Monitors the router_decisions.jsonl log file for errors (e.g. rate limits)
and dynamically self-corrects the routing policies in freellm_router_mvp.py.
"""

import json
import os
import re
import subprocess
import sys
import time

ROUTER_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_FILE = os.path.join(ROUTER_DIR, "freellm_router_mvp.py")
DECISION_LOG = os.path.join(ROUTER_DIR, "router_decisions.jsonl")

def get_current_policies() -> dict:
    with open(PROXY_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r"V2_POLICIES = (\{.*?\})", content, re.DOTALL)
    if not match:
        raise RuntimeError("Could not find V2_POLICIES dict in proxy file")
    return eval(match.group(1))

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

def restart_proxies():
    print("[Self-Healer] Restarting single Auto Mode (v4) proxy on port 8792...")
    subprocess.run("ps aux | grep freellm_router_mvp.py | grep -v grep | awk '{print $2}' | xargs kill -9 || true", shell=True)
    subprocess.run("/Users/robinsverd/.local/bin/claude-router --mode v4 --start-proxy", shell=True)

def run_self_healing():
    if not os.path.exists(DECISION_LOG):
        return

    print("[Self-Healer] Scanning decisions log for recent rate-limit and routing failures...")
    
    # Read last 50 decisions
    with open(DECISION_LOG, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    recent_decisions = []
    for line in lines[-50:]:
        try:
            recent_decisions.append(json.loads(line))
        except:
            pass

    failures_by_policy = {}
    
    for dec in recent_decisions:
        status = dec.get("status")
        notes = dec.get("fallback_notes", "")
        policy = dec.get("policy", "")
        if policy.startswith("ensemble:"):
            policy = policy[9:]

        if status == "error" and dec.get("error_message"):
            err_msg = dec["error_message"]
            failed_models = re.findall(r"([\w\-/:.:]+) \(attempt \d+\):", err_msg)
            if failed_models and policy:
                if policy not in failures_by_policy:
                    failures_by_policy[policy] = []
                failures_by_policy[policy].extend(failed_models)
                
        if notes:
            failed_models = re.findall(r"([\w\-/:.:]+) \(attempt \d+\):", notes)
            if failed_models and policy:
                if policy not in failures_by_policy:
                    failures_by_policy[policy] = []
                failures_by_policy[policy].extend(failed_models)

    if not failures_by_policy:
        print("[Self-Healer] No recent routing failures or fallback delays detected. System is healthy.")
        return

    policies = get_current_policies()
    modified = False
    
    for policy, failed_list in failures_by_policy.items():
        if policy not in policies:
            continue
        model_list = list(policies[policy])
        unique_failures = list(dict.fromkeys(failed_list))
        
        for failed_model in unique_failures:
            if failed_model in model_list and model_list[0] == failed_model:
                print(f"[Self-Healer] ACTION: Shifting rate-limiting model '{failed_model}' to the end of policy '{policy}'")
                model_list.remove(failed_model)
                model_list.append(failed_model)
                modified = True
                
        policies[policy] = model_list

    if modified:
        write_policies(policies)
        restart_proxies()
        print("[Self-Healer] Auto-optimization completed successfully!")
    else:
        print("[Self-Healer] Failing models have already been moved to the end of the fallback queue.")

if __name__ == "__main__":
    run_self_healing()
