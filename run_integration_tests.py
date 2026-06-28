#!/usr/bin/env python3
"""
Integration test suite for FreeLLM Claude Router.
Verifies all 4 proxy versions (v1, v2, v3, v4) against their expected behaviors,
response headers, and output log generation.
"""

import json
import os
import urllib.request
import urllib.error
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(SCRIPT_DIR, "router_decisions.jsonl")

PORTS = {
    "v1": 8787,
    "v2": 8791,
    "v3": 8789,
    "v4": 8792
}

def send_post(port: int, path: str, payload: dict) -> tuple[int, dict, dict]:
    url = f"http://127.0.0.1:{port}{path}"
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            res_headers = {k.lower(): v for k, v in res.getheaders()}
            body = json.loads(res.read().decode("utf-8"))
            return res.status, body, res_headers
    except urllib.error.HTTPError as err:
        try:
            body = json.loads(err.read().decode("utf-8"))
        except Exception:
            body = {"error": err.reason}
        return err.code, body, {k.lower(): v for k, v in err.headers.items()}
    except Exception as err:
        return 500, {"error": str(err)}, {}

def check_port_listening(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0

def test_v1() -> None:
    print("\n--- Testing Version 1 (Port 8787) ---")
    port = PORTS["v1"]
    if not check_port_listening(port):
        print(f"Skipping v1: Port {port} not listening.")
        return

    payload = {
        "model": "qwen/qwen3-coder:free",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "Reply with exactly: V1_INTEGRATION_TEST_OK"}]
    }
    status, body, headers = send_post(port, "/v1/messages", payload)
    assert status == 200, f"v1 request failed with status {status}: {body}"
    assert "v1" in headers.get("x-router-mode", ""), f"Unexpected x-router-mode header: {headers}"
    print("v1 test passed successfully.")

def test_v2() -> None:
    print("\n--- Testing Version 2 (Port 8791) ---")
    port = PORTS["v2"]
    if not check_port_listening(port):
        print(f"Skipping v2: Port {port} not listening.")
        return

    # 1. Test coding query
    payload_coding = {
        "model": "qwen/qwen3-coder:free",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "Write a python function that returns 42."}]
    }
    status, body, headers = send_post(port, "/v1/messages", payload_coding)
    assert status == 200, f"v2 coding request failed: {body}"
    assert headers.get("x-router-policy") == "coding", f"Expected coding policy, got: {headers.get('x-router-policy')}"

    # 2. Test summarization query
    payload_sum = {
        "model": "qwen/qwen3-coder:free",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "Summarize the history of Python in one sentence."}]
    }
    status, body, headers = send_post(port, "/v1/messages", payload_sum)
    assert status == 200, f"v2 summarization request failed: {body}"
    assert headers.get("x-router-policy") == "summarization", f"Expected summarization policy, got: {headers.get('x-router-policy')}"

    print("v2 tests passed successfully.")

def test_v3() -> None:
    print("\n--- Testing Version 3 (Port 8789) ---")
    port = PORTS["v3"]
    if not check_port_listening(port):
        print(f"Skipping v3: Port {port} not listening.")
        return

    # Text-only query should trigger ensemble
    payload = {
        "model": "qwen/qwen3-coder:free",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "Explain the difference between a router and a switch."}]
    }
    status, body, headers = send_post(port, "/v1/messages", payload)
    assert status == 200, f"v3 request failed: {body}"
    assert "ensemble" in headers.get("x-router-policy", ""), f"Expected ensemble policy, got: {headers.get('x-router-policy')}"
    assert headers.get("x-router-advisor-models") is not None, "Expected advisor models list header"
    print("v3 test passed successfully.")

def test_v4() -> None:
    print("\n--- Testing Version 4 (Port 8792) ---")
    port = PORTS["v4"]
    if not check_port_listening(port):
        print(f"Skipping v4: Port {port} not listening.")
        return

    # 1. Simple query -> should map to v1
    payload_simple = {
        "model": "qwen/qwen3-coder:free",
        "max_tokens": 30,
        "messages": [{"role": "user", "content": "Say hi."}]
    }
    status, body, headers = send_post(port, "/v1/messages", payload_simple)
    assert status == 200, f"v4 simple request failed: {body}"
    assert headers.get("x-router-selected-version") == "v1", f"Expected v1 routing, got: {headers.get('x-router-selected-version')}"

    # 2. Tool-bearing query -> should map to v2
    payload_tool = {
        "model": "qwen/qwen3-coder:free",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "Use tool ping."}],
        "tools": [
            {
                "name": "ping",
                "description": "Ping",
                "input_schema": {"type": "object"}
            }
        ]
    }
    status, body, headers = send_post(port, "/v1/messages", payload_tool)
    assert status == 200, f"v4 tool request failed: {body}"
    assert headers.get("x-router-selected-version") == "v2", f"Expected v2 routing for tools, got: {headers.get('x-router-selected-version')}"

    # 3. Design pattern / comparison query -> should map to v3
    payload_compare = {
        "model": "qwen/qwen3-coder:free",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "What is the difference between REST and GraphQL?"}]
    }
    status, body, headers = send_post(port, "/v1/messages", payload_compare)
    assert status == 200, f"v4 compare request failed: {body}"
    assert headers.get("x-router-selected-version") == "v3", f"Expected v3 routing for comparison, got: {headers.get('x-router-selected-version')}"

    print("v4 tests passed successfully.")

def verify_decision_logs() -> None:
    print("\n--- Verifying Decision Logs ---")
    if not os.path.exists(LOG_FILE_PATH):
        raise AssertionError(f"Log file not found at: {LOG_FILE_PATH}")

    # Read last 5 logs
    logs = []
    with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                logs.append(json.loads(line))

    assert len(logs) > 0, "No log entries found in router_decisions.jsonl"
    print(f"Verified {len(logs)} log entries in router_decisions.jsonl. Example log:")
    print(json.dumps(logs[-1], indent=2))

def main() -> None:
    print("Starting FreeLLM Claude Router Integration Tests...")
    
    # Keep track of initial log line count
    initial_log_lines = 0
    if os.path.exists(LOG_FILE_PATH):
        with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
            initial_log_lines = sum(1 for line in f if line.strip())

    test_v1()
    test_v2()
    test_v3()
    test_v4()
    
    # Wait a moment for file flushing
    time.sleep(0.5)
    verify_decision_logs()
    
    if os.path.exists(LOG_FILE_PATH):
        with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
            final_log_lines = sum(1 for line in f if line.strip())
        print(f"\nIntegration test run appended {final_log_lines - initial_log_lines} new log lines.")
        
    print("\nAll integration tests passed successfully!")

if __name__ == "__main__":
    main()
