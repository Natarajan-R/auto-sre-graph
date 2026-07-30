"""
Auto-SRE-Graph — Functional Demo Scenarios

Demonstrates the complete power of the system through 10 real-world SRE scenarios.
Run against a running API:  python demo_scenarios.py

Each scenario is independent and can be run individually:
  python demo_scenarios.py 2 5 9     # run scenarios 2, 5, 9 only
  python demo_scenarios.py           # run all 10
  python demo_scenarios.py -h        # help

Uses the HTTP API only; no internal imports.
"""

import json
import time
import sys
import urllib.request
import urllib.error

API = "http://localhost:8000"
API_KEY = "your-api-key"

SEP = "=" * 78
PAD = "  "


def req(method, path, body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY,
    }
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read()
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            detail = detail.decode()
        return e.code, detail


def wait_for_status(alert_id, poll_sec=3, max_wait=60):
    """Poll /status/{alert_id} until a real workflow state appears or times out."""
    for i in range(max_wait // poll_sec):
        status_code, data = req("GET", f"/status/{alert_id}")
        if status_code == 200:
            state = data.get("state", {})
            # A real workflow state has at least 'alert' or 'final_status'
            if state.get("alert") or state.get("final_status"):
                return data
            if i == 0:
                print(f"{PAD}⏳ Workflow still initializing...")
        else:
            if i == 0:
                print(f"{PAD}⏳ Waiting for workflow to start...")
        time.sleep(poll_sec)
    return {"thread_id": alert_id, "status": "TIMEOUT", "_note": "Workflow did not produce state within wait window"}


def print_header(num, title, detail=""):
    print(f"\n{SEP}")
    print(f"  ▶  SCENARIO {num}: {title}")
    print(f"{SEP}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"     {line}")
    print()


def print_response(label, status_code, data):
    print(f"{PAD}[{status_code}] {label}")
    printed = json.dumps(data, indent=4, default=str)
    for line in printed.split("\n"):
        print(f"{PAD} {line}")
    print()


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 1 — Health Check & System Readiness
# ────────────────────────────────────────────────────────────────────────────

def scenario_1():
    print_header(1, "Health Check & System Readiness",
                 "Verify all components are running and the API is healthy.")

    status, data = req("GET", "/health")
    print_response("GET /health", status, data)

    status, data = req("GET", "/metrics")
    print_response("GET /metrics (before any ingestion)", status, data)


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 2 — Standard Alert → Full Workflow
# ────────────────────────────────────────────────────────────────────────────

def scenario_2():
    print_header(2, "Standard Alert Ingestion & Full Workflow",
                 "A typical HIGH-severity alert from auth-service in SIT.\n"
                 "Runs the full pipeline: validation → dedup → context retrieval\n"
                 "→ AI diagnosis → routing (escalate / create Jira ticket / error).")

    payload = {
        "alert_id": "SCENARIO-002",
        "environment": "SIT",
        "service_name": "auth-service",
        "error_message": "Connection timeout to database: Connection refused after 30s",
        "stack_trace": (
            'Traceback (most recent call last):\n'
            '  File "/app/auth/db.py", line 45, in connect\n'
            '    raise ConnectionError("Connection refused")\n'
            'psycopg2.OperationalError: connection to server at 10.0.1.50, '
            'port 5432 failed: Connection refused'
        ),
        "severity": "HIGH",
        "git_commit_hash": "a1b2c3d4e5f6",
    }
    status, data = req("POST", "/webhooks/ado", payload)
    print_response("POST /webhooks/ado", status, data)

    state = wait_for_status("SCENARIO-002")
    print_response("GET /status/SCENARIO-002 (workflow result)", 200, state)


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 3 — Critical PROD Incident (High Priority)
# ────────────────────────────────────────────────────────────────────────────

def scenario_3():
    print_header(3, "Critical PROD Incident — Payment Service Down",
                 "A CRITICAL alert from PROD triggers the highest-priority workflow.\n"
                 "The system creates a Jira ticket and pauses for human approval\n"
                 "before allowing any remediation action.")

    payload = {
        "alert_id": "SCENARIO-003",
        "environment": "PROD",
        "service_name": "payment-service",
        "error_message": "Payment gateway timeout: upstream service unavailable after 60s retries exhausted",
        "stack_trace": (
            'Traceback:\n'
            '  File "/app/payment/gateway.py", line 120, in process_payment\n'
            '    raise TimeoutError("Gateway timeout")\n'
            '  File "/app/payment/gateway.py", line 85, in _retry_with_backoff\n'
            '    raise TimeoutError("Retries exhausted after 3 attempts")'
        ),
        "severity": "CRITICAL",
        "git_commit_hash": "a1b2c3d4e5f6",
    }
    status, data = req("POST", "/webhooks/ado", payload)
    print_response("POST /webhooks/ado", status, data)

    state = wait_for_status("SCENARIO-003")
    print_response("GET /status/SCENARIO-003 (workflow result)", 200, state)


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 4 — Duplicate Alert Detection
# ────────────────────────────────────────────────────────────────────────────

def scenario_4():
    print_header(4, "Duplicate Alert Detection",
                 "Send the same alert_id twice. The second attempt is filtered\n"
                 "by the in-memory deduplication layer before any workflow starts.\n"
                 "Note: with 4 API workers this is best-effort per-process;\n"
                 "the Redis-backed SHA-256 dedup in the workflow is authoritative.")

    payload = {
        "alert_id": "SCENARIO-004",
        "environment": "SIT",
        "service_name": "user-service",
        "error_message": "High CPU usage detected: 95% on pod user-service-7f8b9c",
        "stack_trace": "Warning: CPU threshold exceeded at Namespace: production Pod: user-service-7f8b9c",
        "severity": "MEDIUM",
        "git_commit_hash": "a1b2c3d4e5f6",
    }

    status, data = req("POST", "/webhooks/ado", payload)
    print_response("POST /webhooks/ado (first ingestion)", status, data)

    status, data = req("POST", "/webhooks/ado", payload)
    print_response("POST /webhooks/ado (second — should read 'filtered')", status, data)


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 5 — Noisy Alert Filtering
# ────────────────────────────────────────────────────────────────────────────

def scenario_5():
    print_header(5, "Noisy Alert Filtering",
                 "Alerts matching known noisy keywords (e.g. 'disk space warning')\n"
                 "are dropped before entering the workflow pipeline. This prevents\n"
                 "alert fatigue and saves LLM costs.")

    payload = {
        "alert_id": "SCENARIO-005",
        "environment": "DEV",
        "service_name": "logging-service",
        "error_message": "Disk space warning: 85% on /var/log volume — automatic cleanup triggered",
        "stack_trace": "Warning: /dev/sda1 at 85% capacity. Action: logrotate will free space",
        "severity": "LOW",
        "git_commit_hash": "a1b2c3d4e5f6",
    }
    status, data = req("POST", "/webhooks/ado", payload)

    # If AlertFilter.keywords_to_drop is configured, this is "filtered";
    # otherwise it falls through to the workflow (which we show too).
    note = ""
    if status == 200 and data.get("status") == "filtered":
        pass
    elif status == 200:
        note = "  (alert was accepted — configure AlertFilter.keywords_to_drop for filtering)"

    print_response("POST /webhooks/ado (noisy alert)" + note, status, data)


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 6 — Payload Validation Errors
# ────────────────────────────────────────────────────────────────────────────

def scenario_6():
    print_header(6, "Payload Validation Errors",
                 "The API rejects malformed or invalid payloads at the Pydantic layer\n"
                 "with descriptive error messages before any processing occurs.")

    # Missing required fields
    payload = {
        "alert_id": "SCENARIO-006",
        "environment": "SIT",
    }
    status, data = req("POST", "/webhooks/ado", payload)
    print_response("Missing required fields (service_name, error_message, severity)", status, data)

    # Invalid enum value
    payload = {
        "alert_id": "SCENARIO-007",
        "environment": "INVALID_ENV",
        "service_name": "auth-service",
        "error_message": "Something went wrong in the system",
        "severity": "HIGH",
        "git_commit_hash": "a1b2c3d4e5f6",
    }
    status, data = req("POST", "/webhooks/ado", payload)
    print_response("Invalid environment enum value", status, data)

    # Error message too short
    payload = {
        "alert_id": "SCENARIO-008",
        "environment": "SIT",
        "service_name": "auth-service",
        "error_message": "short",
        "severity": "HIGH",
        "git_commit_hash": "a1b2c3d4e5f6",
    }
    status, data = req("POST", "/webhooks/ado", payload)
    print_response("Error message too short (< 10 chars)", status, data)


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 7 — Sensitive Data Redaction
# ────────────────────────────────────────────────────────────────────────────

def scenario_7():
    print_header(7, "Sensitive Data Redaction",
                 "The validation layer automatically redacts passwords, tokens,\n"
                 "secrets, and API keys from the payload before it reaches the workflow.")

    payload = {
        "alert_id": "SCENARIO-009",
        "environment": "SIT",
        "service_name": "auth-service",
        "error_message": "Authentication failure: invalid credentials provided",
        "stack_trace": "Login failed for user admin from 10.0.1.100",
        "severity": "MEDIUM",
        "git_commit_hash": "a1b2c3d4e5f6",
        "additional_context": {
            "db_password": "supersecret123",
            "api_token": "sk-live-abc123def456",
            "connection_secret": "prod-cert-2024",
            "host": "db-primary.internal",
            "port": 5432,
        },
    }
    status, data = req("POST", "/webhooks/ado", payload)
    print_response("POST /webhooks/ado (sensitive data in additional_context)", status, data)

    if status == 200:
        state = wait_for_status("SCENARIO-009")
        print_response("GET /status/SCENARIO-009 (values should be ***REDACTED***)", 200, state)


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 8 — Complex Multi-Error Alert
# ────────────────────────────────────────────────────────────────────────────

def scenario_8():
    print_header(8, "Complex Multi-Error Alert",
                 "An order-service alert with cascading failures: DB + Redis + API\n"
                 "all failing simultaneously. Tests the system's ability to handle\n"
                 "rich context and produce a comprehensive diagnosis.")

    payload = {
        "alert_id": "SCENARIO-010",
        "environment": "UAT",
        "service_name": "order-service",
        "error_message": "Order processing pipeline: DB connection lost → Redis cache miss → downstream API 503",
        "stack_trace": (
            "ERROR 1 — Database: connection to server at 10.0.1.50, port 5432 failed\n"
            "ERROR 2 — Redis: Timeout connecting to redis://10.0.1.60:6379 after 5s\n"
            "ERROR 3 — Shipping API: POST https://shipping.internal/api/v2/orders → HTTP 503\n"
            '  File "/app/order/pipeline.py", line 201, in process_order\n'
            '    raise PipelineError(f"Stage {stage} failed: {error}")\n'
            "Backend Error: psycopg2.OperationalError: connection refused"
        ),
        "severity": "CRITICAL",
        "git_commit_hash": "a1b2c3d4e5f6",
        "service_version": "v2.3.1",
    }
    status, data = req("POST", "/webhooks/ado", payload)
    print_response("POST /webhooks/ado (complex multi-error)", status, data)

    state = wait_for_status("SCENARIO-010")
    print_response("GET /status/SCENARIO-010 (workflow result)", 200, state)


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 9 — System Metrics Dashboard
# ────────────────────────────────────────────────────────────────────────────

def scenario_9():
    print_header(9, "System Metrics Dashboard",
                 "Query the system's operational metrics after multiple alerts.\n"
                 "Shows ingested count, workflow statuses, error counts, and uptime.")

    for alert_id in ["SCENARIO-002", "SCENARIO-003", "SCENARIO-004", "SCENARIO-009", "SCENARIO-010"]:
        status, data = req("GET", f"/status/{alert_id}")
        if status == 200:
            label = data.get("status", "unknown")
        else:
            label = data.get("detail", str(status))
        print(f"  [{status}] GET /status/{alert_id:20s} → {label}")

    print()
    status, data = req("GET", "/metrics")
    print_response("GET /metrics (cumulative)", status, data)


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 10 — Error Recovery: Circuit Breaker Simulation
# ────────────────────────────────────────────────────────────────────────────

def scenario_10():
    print_header(10, "Error Recovery",
                 "The system handles external service failures gracefully using\n"
                 "circuit breakers (5 failures → OPEN → 60s timeout → HALF_OPEN).\n"
                 "If the context retrieval or LLM fails, the workflow continues\n"
                 "with partial data and records the error in the workflow state.")

    payload = {
        "alert_id": "SCENARIO-011",
        "environment": "PROD",
        "service_name": "unknown-service-v2",
        "error_message": "Segmentation fault in worker process: signal 11 received",
        "stack_trace": "Fatal: pid 1234 received SIGSEGV at /app/worker/process.py:89 in handle_request",
        "severity": "CRITICAL",
        "git_commit_hash": "a1b2c3d4e5f6",
    }
    status, data = req("POST", "/webhooks/ado", payload)
    print_response("POST /webhooks/ado (unknown service — still accepted if ALLOWED_SERVICES is empty)", status, data)

    print(f"{PAD}Workflow nodes are wrapped in try/except. If a node fails:")
    print(f"{PAD}  1. The error is caught and logged")
    print(f"{PAD}  2. Circuit breaker increments failure count")
    print(f"{PAD}  3. The workflow continues with partial/fallback data")
    print(f"{PAD}  4. The error is recorded in error_messages[]")
    print(f"{PAD}  5. After 3+ node failures, the workflow routes to handle_error")
    print()

    if status == 200:
        state = wait_for_status("SCENARIO-011")
        print_response("GET /status/SCENARIO-011 (check error_count & error_messages)", 200, state)


# ────────────────────────────────────────────────────────────────────────────
# SCENARIO 11 — Log Tripwire Ingestion
# ────────────────────────────────────────────────────────────────────────────

def scenario_11():
    print_header(11, "Log Tripwire Ingestion",
                 "Simulates the tripwire sidecar dispatching a raw log match.\n"
                 "The tripwire reads a log file, matches an error pattern,\n"
                 "captures the stack trace, and POSTs to /webhooks/tripwire.\n"
                 "This scenario sends the same format the tripwire would.")

    payload = {
        "alert_id": "SCENARIO-TRIPWIRE-001",
        "environment": "PROD",
        "service_name": "legacy-monolith",
        "severity": "HIGH",
        "error_message": "FATAL: ConnectionTimeoutError — upstream service db-primary:5432 unreachable",
        "stack_trace": (
            '2026-07-30 10:15:23 ERROR [main] c.d.pool.ConnectionPool: '
            'Connection to db-primary:5432 failed (attempt 1/3)\n'
            '2026-07-30 10:15:28 ERROR [main] c.d.pool.ConnectionPool: '
            'Connection to db-primary:5432 failed (attempt 2/3)\n'
            '2026-07-30 10:15:33 FATAL [main] c.d.pool.ConnectionPool: '
            'All 3 connection attempts exhausted. Shutting down worker pool.'
        ),
    }
    status, data = req("POST", "/webhooks/tripwire", payload)
    print_response("POST /webhooks/tripwire (tripwire-style payload)", status, data)

    state = wait_for_status("SCENARIO-TRIPWIRE-001")
    print_response("GET /status/SCENARIO-TRIPWIRE-001 (workflow result)", 200, state)


# ────────────────────────────────────────────────────────────────────────────
# RUNNER
# ────────────────────────────────────────────────────────────────────────────

SCENARIOS = [
    ("1  — Health Check & System Readiness",         scenario_1),
    ("2  — Standard Alert → Full Workflow",          scenario_2),
    ("3  — Critical PROD Incident",                  scenario_3),
    ("4  — Duplicate Alert Detection",               scenario_4),
    ("5  — Noisy Alert Filtering",                   scenario_5),
    ("6  — Payload Validation Errors",               scenario_6),
    ("7  — Sensitive Data Redaction",                scenario_7),
    ("8  — Complex Multi-Error Alert",               scenario_8),
    ("9  — System Metrics Dashboard",                scenario_9),
    ("10 — Error Recovery & Circuit Breakers",       scenario_10),
    ("11 — Log Tripwire Ingestion",                  scenario_11),
]

DEFAULT_RUN = list(range(len(SCENARIOS)))


def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print("Usage: python demo_scenarios.py [scenario_numbers...]")
        print()
        print("Examples:")
        print("  python demo_scenarios.py          # run all 10 scenarios")
        print("  python demo_scenarios.py 2 5 9     # run scenarios 2, 5, 9 only")
        print()
        print("Scenarios:")
        for i, (title, _) in enumerate(SCENARIOS):
            print(f"  {i+1:2d}. {title}")
        sys.exit(0)

    if args:
        indices = [int(a) - 1 for a in args if a.isdigit()]
    else:
        indices = DEFAULT_RUN

    print()
    print("╔" + "═" * 76 + "╗")
    print("║" + "  Auto-SRE-Graph — Functional Demo Scenarios".center(74) + "║")
    print("║" + f"  API: {API}".ljust(74) + "║")
    print("╚" + "═" * 76 + "╝")
    print()

    for i in indices:
        if 0 <= i < len(SCENARIOS):
            title, fn = SCENARIOS[i]
            try:
                fn()
            except Exception as e:
                print(f"{PAD}⚠  Scenario {i+1} raised exception: {e}")
            print()
        else:
            print(f"{PAD}⚠  Unknown scenario number: {i+1}")

    print(f"\n{SEP}")
    print("  Demo complete.")
    print(f"{SEP}\n")


if __name__ == "__main__":
    main()
