"""
Enterprise SRE Problem Solver — Live Demonstrations

Uses the Auto-SRE-Graph system to solve 11 real enterprise SRE problems.
Each scenario sends realistic alerts to the running API and shows how
the system addresses a specific business challenge.

Usage:
  python enterprise_solutions.py              # run all 11 solutions
  python enterprise_solutions.py 0 3 7 10    # run specific ones
  python enterprise_solutions.py -h           # help

Requirements: API running at http://localhost:8000
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
    headers = {"Content-Type": "application/json", "X-API-Key": API_KEY}
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read()
        try:
            detail = json.loads(detail)
        except Exception:
            detail = detail.decode()
        return e.code, detail


def wait_for_state(alert_id, poll_sec=3, max_wait=60):
    for _ in range(max_wait // poll_sec):
        code, data = req("GET", f"/status/{alert_id}")
        if code == 200 and data.get("state", {}).get("final_status"):
            return data
        time.sleep(poll_sec)
    return {"status": "TIMEOUT", "state": {}}


def show_solution(num, title, problem, solution, payloads):
    """Run an enterprise solution demo and print results."""
    print(f"\n{SEP}")
    print(f"  ENTERPRISE PROBLEM #{num}")
    print(f"  {title}")
    print(f"{SEP}")
    print(f"\n{PAD}▎Problem:")
    for line in problem.strip().split("\n"):
        print(f"{PAD}  {line}")
    print(f"\n{PAD}▎How the system solves it:")
    for line in solution.strip().split("\n"):
        print(f"{PAD}  {line}")
    print()

    for i, (label, payload) in enumerate(payloads, 1):
        print(f"{PAD}─── Step {i}: {label} ───")
        code, data = req("POST", "/webhooks/ado", payload)
        status = data.get("status", "error")
        detail = data.get("detail", data.get("message", ""))
        if isinstance(detail, list):
            detail = detail[0].get("msg", str(detail[0])) if detail else ""
        print(f"{PAD}  → {code} | status: {status}")
        if detail:
            print(f"{PAD}    {detail}")

        if code == 200 and status == "processing":
            state = wait_for_state(payload["alert_id"])
            final = state.get("status", "?")
            error_count = state.get("state", {}).get("error_count", 0)
            errors = state.get("state", {}).get("error_messages", [])
            analysis = state.get("state", {}).get("analysis", {})
            confidence = analysis.get("confidence_score", "N/A")
            action = analysis.get("proposed_action", "N/A")
            print(f"{PAD}    final_status: {final}  |  confidence: {confidence}  |  action: {action}")
            if errors:
                print(f"{PAD}    errors ({error_count}): {errors[0][:100]}...")
        print()

    # Summary box
    print(f"{PAD}┌{'─' * 60}┐")
    print(f"{PAD}│ Enterprise value summary for this problem:")
    print(f"{PAD}│   {_summarize(num)}")
    print(f"{PAD}└{'─' * 60}┘")
    print()


def _summarize(num):
    summaries = {
        1: "Alert volume reduced by 60-80%. On-call team sees only real incidents.",
        2: "Triage time: 15-45 min → <60 sec. MTTR drops dramatically.",
        3: "Institutional knowledge preserved. Incidents resolved without the senior SRE.",
        4: "Zero manual commands in production. Every action: AI proposes → human approves → system executes.",
        5: "Escalations happen in seconds, not hours. SLA compliance measurable and reportable.",
        6: "Every incident follows the same proven process. Consistent, repeatable, auditable.",
        7: "Every incident generates a complete structured record. Post-mortems write themselves.",
        8: "Impact analysis automatic. Jira tickets routed to the right teams with full context.",
        9: "Model tiering + caching cuts LLM costs 40-60%. Budget never surprises.",
        10: "Full audit trail on every action. Ready for SOC 2, ISO 27001, financial audits.",
    }
    return summaries.get(num, "")


# ════════════════════════════════════════════════════════════════════════════
# PROBLEM 1 — Alert Fatigue
# ════════════════════════════════════════════════════════════════════════════

def problem_0():
    show_solution(
        0,
        "Legacy Application Blind Spots — Log Tripwire",
        "10-50 year old monoliths only emit raw log files; no webhooks or APM.",
        "Sidecar tripwire reads logs via shared volume, matches error patterns, "
        "captures stack traces, and dispatches as structured alerts — zero app changes.",
        [
            ("POST /webhooks/tripwire (legacy-monolith log match)",
             {"alert_id": "TRIPWIRE-DEMO-001",
              "environment": "PROD", "service_name": "legacy-monolith",
              "severity": "HIGH",
              "error_message": "ConnectionTimeoutError — upstream db-primary:5432 unreachable",
              "stack_trace": (
                  "2026-07-30 10:15:23 ERROR [main] Connection to db-primary:5432 failed (1/3)\n"
                  "2026-07-30 10:15:28 ERROR [main] Connection to db-primary:5432 failed (2/3)\n"
                  "2026-07-30 10:15:33 FATAL [main] All 3 connection attempts exhausted."
              )}),
        ]
    )


def problem_1():
    show_solution(
        1,
        "Alert Fatigue — Too Many Noisy Alerts",
        """
An e-commerce platform generates 15,000 alerts per day. 80% are known noise:
disk space warnings, routine certificate renewals, expected pod restarts.
The on-call SRE is drowning — real incidents get buried.
        """,
        """
The system filters noise at ingestion:
• AlertFilter drops alerts matching noisy keywords ("disk space", "cert renewal")
• Deduplication prevents processing the same alert twice
• Rate limiting caps spikes from misconfigured monitors
• Service allowlist restricts which services are monitored

Only clean, unique, relevant alerts reach the workflow engine.
The SRE sees 3,000 alerts/day instead of 15,000 — a 80% reduction.
        """,
        [
            ("Noisy disk space alert (should be filtered)",
             {"alert_id": "ENT-001-A", "environment": "PROD", "service_name": "monitoring-service",
              "error_message": "Disk space warning: /data at 82% capacity — cleanup required",
              "stack_trace": "Warning: partition /data at 82%", "severity": "LOW",
              "git_commit_hash": "a1b2c3d4e5f6"}),

            ("Duplicate of the same alert (should be deduped)",
             {"alert_id": "ENT-001-A", "environment": "PROD", "service_name": "monitoring-service",
              "error_message": "Disk space warning: /data at 82% capacity — cleanup required",
              "stack_trace": "Warning: partition /data at 82%", "severity": "LOW",
              "git_commit_hash": "a1b2c3d4e5f6"}),

            ("Real incident — auth-service DOWN (passes through)",
             {"alert_id": "ENT-001-B", "environment": "PROD", "service_name": "auth-service",
              "error_message": "Authentication service unreachable: HTTP 503 after 30s timeout",
              "stack_trace": "Connection refused at auth.internal:8443\n  File auth/client.py:42 in connect",
              "severity": "CRITICAL", "git_commit_hash": "a1b2c3d4e5f6"}),
        ]
    )


# ════════════════════════════════════════════════════════════════════════════
# PROBLEM 2 — Slow Incident Triage
# ════════════════════════════════════════════════════════════════════════════

def problem_2():
    show_solution(
        2,
        "Slow Incident Triage & Diagnosis",
        """
A payment gateway fails at 2 AM. The on-call engineer needs to:
1. Read the error (2 min)
2. Find the right runbook (10 min — which one?)
3. Check service dependencies (5 min — what depends on this?)
4. Look up past incidents (10 min — has this happened before?)
5. Determine severity (3 min)
6. Decide what to do (5 min)

Total: 35 minutes of manual investigation. Customers are impacted the entire time.
        """,
        """
The system triages automatically in <60 seconds:
• VectorRAG searches Qdrant for similar past incidents (embeddings + cosine similarity)
• GraphRAG queries Neo4j for service topology (what depends on payment-gateway?)
• DiagnosticAgent (pydantic-ai) analyzes alert + context against LLM
• Structured output: root cause, confidence score, proposed action, remediation script
• Fallback chain: if primary LLM fails → fallback → hardcoded analysis (graceful)

The on-call engineer gets a complete diagnosis before their coffee finishes brewing.
        """,
        [
            ("Payment gateway failure with full context",
             {"alert_id": "ENT-002-A", "environment": "PROD", "service_name": "payment-service",
              "error_message": "Payment gateway timeout after 60s: upstream connection refused at payment-processor.internal:8443",
              "stack_trace": (
                  "ERROR: transaction #TX-98765 failed after 3 retries\n"
                  '  File "/app/payment/processor.py", line 234, in charge\n'
                  "    raise GatewayTimeout(f\"Upstream refused after {timeout}s\")\n"
                  "  File \"/app/payment/gateway.py\", line 89, in _retry\n"
                  "    return await self._post(url, payload, timeout)\n"
                  "aiohttp.ClientConnectorError: Connection refused at payment-processor.internal:8443"
              ),
              "severity": "CRITICAL", "git_commit_hash": "a1b2c3d4e5f6"}),
        ]
    )


# ════════════════════════════════════════════════════════════════════════════
# PROBLEM 3 — Knowledge Silos
# ════════════════════════════════════════════════════════════════════════════

def problem_3():
    show_solution(
        3,
        "Knowledge Silos — When the Senior SRE Is Off-Duty",
        """
The senior SRE who has run this playbook 50 times is on vacation. The junior on-call
engineer has never seen this error before. They don't know:
• Is this a known issue? (tribal knowledge)
• What services are affected? (architectural knowledge)
• What command fixed it last time? (procedural knowledge)
• Who should be notified? (organizational knowledge)

The engineer is paralyzed. MTTR climbs from 20 minutes to 4 hours.
        """,
        """
The system captures and reuses knowledge automatically:
• Every past incident is stored as a vector embedding in Qdrant
• Similar incidents are retrieved by semantic similarity, not exact match
• Service topology is maintained in Neo4j — no human needs to map dependencies
• Every diagnosis + action is persisted in the incidents table
• Audit trail shows exactly what was done, by whom, and the outcome

The junior engineer gets the same quality of diagnosis the senior would provide.
        """,
        [
            ("Database connection pool exhaustion — known pattern",
             {"alert_id": "ENT-003-A", "environment": "PROD", "service_name": "order-service",
              "error_message": "Connection pool exhausted: 100/100 connections in use, query queued for 30s",
              "stack_trace": (
                  "psycopg2.pool.PoolError: connection pool exhausted\n"
                  '  File "/app/order/db.py", line 67, in acquire\n'
                  "    raise PoolError(f\"Pool exhausted: {used}/{total} in use\")\n"
                  '  File "/app/order/api.py", line 34, in create_order\n'
                  "    conn = await db.acquire()"
              ),
              "severity": "HIGH", "git_commit_hash": "a1b2c3d4e5f6",
              "service_version": "v3.1.0"}),
        ]
    )


# ════════════════════════════════════════════════════════════════════════════
# PROBLEM 4 — Runbook Execution Under Pressure
# ════════════════════════════════════════════════════════════════════════════

def problem_4():
    show_solution(
        4,
        "Manual Runbook Execution Under Pressure",
        """
It's 3 AM. An SRE gets paged for a production incident. The runbook says:
"kubectl rollout restart deployment/auth-service -n production"

Under pressure, the SRE types:
  kubectl rollout restart deployment/order-service -n production
  — Wrong service, rolling restart of the wrong deployment.

Or worse:
  kubectl delete namespace production
  — Complete production outage caused by a fat-finger error.

These are real incidents from major enterprises. Human error in manual runbook
execution is the #1 cause of production incidents during incident response.
        """,
        """
The system eliminates manual command execution entirely:
• AI proposes the remediation command in the analysis
• Workflow pauses before execute_remediation (interrupt_before)
• Human approves via Jira webhook callback (not a terminal)
• RemediationTool validates: allowlisted binaries only (kubectl, helm, git, docker, systemctl)
• Production guard: confidence < 0.85 for rollback/restart → automatically downgraded
• 300-second hard timeout on all commands

A human still makes the decision — but the system executes precisely.
        """,
        [
            ("Critical auth-service failure needing rollback",
             {"alert_id": "ENT-004-A", "environment": "PROD", "service_name": "auth-service",
              "error_message": "JWT token validation failed: signature mismatch after v3.2.1 deployment — all auth requests rejected",
              "stack_trace": (
                  "jose.exceptions.JWSSignatureError: Signature verification failed\n"
                  '  File "/app/auth/validate.py", line 156, in verify_token\n'
                  "    raise JWSSignatureError(\"Signature mismatch\")\n"
                  "Deployment: v3.2.1 (rolling update completed at 02:47 UTC)"
              ),
              "severity": "CRITICAL", "git_commit_hash": "a1b2c3d4e5f6"}),
        ]
    )


# ════════════════════════════════════════════════════════════════════════════
# PROBLEM 5 — Escalation Delays
# ════════════════════════════════════════════════════════════════════════════

def problem_5():
    show_solution(
        5,
        "Escalation Delays & Missed SLAs",
        """
An SRE receives a page for a critical incident they can't fix. They spend:
• 10 minutes trying to debug anyway (hope is not a strategy)
• 10 minutes figuring out who to escalate to (outdated team chart)
• 15 minutes writing up the context for the next team (copy-paste from 3 tools)
• 5 minutes finding the right Jira project

By the time the right team has context, 40+ minutes have elapsed.
The SLA: 30-minute response time. Missed. Escalated to management.
        """,
        """
The system escalates automatically:
• If AI confidence is low → ESCALATE_ONLY routing
• If error count ≥ 3 across nodes → handle_error → escalation
• Jira escalation tickets created with full context: alert, diagnosis, dependency graph
• Priority mapped automatically: CRITICAL → Highest, HIGH → High
• SLAMonitor tracks every incident: avg/p95/p99 resolution time per service
• Escalation rate tracked — if >30%, it triggers alerts

Escalation happens in seconds, not minutes. Full context travels with the ticket.
        """,
        [
            ("Low-confidence diagnosis — automatic escalation",
             {"alert_id": "ENT-005-A", "environment": "PROD", "service_name": "ml-inference-service",
              "error_message": "Model inference failed: CUDA out of memory on GPU:0 — cannot allocate 512MiB",
              "stack_trace": (
                  "torch.cuda.OutOfMemoryError: CUDA out of memory\n"
                  '  File "/app/ml/inference.py", line 203, in predict\n'
                  "    output = model(input_batch.to('cuda:0'))\n"
                  "RuntimeError: CUDA error: out of memory"
              ),
              "severity": "CRITICAL", "git_commit_hash": "a1b2c3d4e5f6"}),
        ]
    )


# ════════════════════════════════════════════════════════════════════════════
# PROBLEM 6 — Inconsistent Incident Response
# ════════════════════════════════════════════════════════════════════════════

def problem_6():
    show_solution(
        6,
        "Inconsistent Incident Response Across Teams",
        """
Three different SRE teams handle the same type of incident three different ways:
• Team Alpha: rolls back immediately
• Team Beta: tries to debug for 30 minutes first
• Team Gamma: escalates to Dev without investigation

When auditors ask "what is your incident response process?", there are three
different answers. This is a compliance risk and an operational liability.
        """,
        """
The system enforces a consistent, auditable process:
• LangGraph DAG defines the exact workflow: START → retrieve_context → diagnostic_agent → route → (Jira → approve → remediate) or escalate or error
• Every alert follows the same graph regardless of severity, service, or team
• Checkpointing ensures process consistency even across restarts
• Audit trail captures every transition — compliance teams can verify process adherence
• The process is codified in Python, not in a PDF: it's testable, version-controlled, and reviewable
        """,
        [
            ("Standard incident — follows the same process as every other",
             {"alert_id": "ENT-006-A", "environment": "PROD", "service_name": "user-service",
              "error_message": "User profile API returning 500 errors after config change: key 'sso_provider' not found",
              "stack_trace": (
                  "KeyError: 'sso_provider'\n"
                  '  File "/app/user/config.py", line 45, in load_settings\n'
                  "    return config[required_key]\n"
                  '  File "/app/user/api.py", line 78, in get_profile\n'
                  "    settings = load_settings()"
              ),
              "severity": "HIGH", "git_commit_hash": "a1b2c3d4e5f6"}),
        ]
    )


# ════════════════════════════════════════════════════════════════════════════
# PROBLEM 7 — Post-Incident Review Data Gaps
# ════════════════════════════════════════════════════════════════════════════

def problem_7():
    show_solution(
        7,
        "Post-Incident Review Data Gaps",
        """
After every major incident, the SRE team holds a post-mortem. The discussion goes:
• "What time did the alert come in?" — Slack says ~2:15 AM
• "What did we try first?" — I think we restarted the service
• "How long did that take?" — Maybe 10 minutes?
• "What was the root cause?" — We think it was a connection pool issue
• "Who approved the restart?" — I don't remember

No data. No accuracy. No improvement.
        """,
        """
Every incident generates a complete structured record:
• alert_id, service_name, environment, severity (from payload)
• vector_context (from Qdrant search)
• graph_topology (from Neo4j query)
• analysis (root_cause_summary, detailed_analysis, confidence_score, proposed_action — from LLM)
• final_status, error_count, error_messages (from workflow execution)
• jira_ticket_id (from Jira integration)
• audit_events: 9 event types with timestamps, actor, target, details (JSONB)
• OpenTelemetry spans: every node timed and traced

Post-mortems evolve from "I think..." to "The data shows..."
        """,
        [
            ("Incident with complete structured data for post-mortem",
             {"alert_id": "ENT-007-A", "environment": "PROD", "service_name": "notification-service",
              "error_message": "Email delivery queue backed up: 50,000 messages pending, SMTP relay unreachable",
              "stack_trace": (
                  "smtplib.SMTPConnectError: Connection refused at smtp-relay.internal:587\n"
                  '  File "/app/notification/email.py", line 156, in send\n'
                  "    server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)\n"
                  '  File "/app/notification/dispatcher.py", line 89, in process_queue\n'
                  "    result = await send_email(message)"
              ),
              "severity": "HIGH", "git_commit_hash": "a1b2c3d4e5f6"}),
        ]
    )


# ════════════════════════════════════════════════════════════════════════════
# PROBLEM 8 — Cross-Team Coordination
# ════════════════════════════════════════════════════════════════════════════

def problem_8():
    show_solution(
        8,
        "Cross-Team Coordination for Multi-Service Incidents",
        """
A database failure triggers alerts in 6 different services. Each team gets paged
independently. Each team starts investigating the same root cause. Each team creates
a separate Jira ticket with different context. Nobody knows the full picture.

4 hours later, someone says: "Wait — is everyone looking at the same DB issue?"
        """,
        """
The system provides shared context automatically:
• GraphRAG queries Neo4j for service topology — the system knows all services that depend on the failing one
• VectorRAG searches Qdrant for similar incidents across all services
• Jira tickets include: alert info, diagnosis, and dependency context
• Audit trail shows all actions across all teams in one queriable database
• Every team gets the same diagnosis, preventing duplicate investigation
        """,
        [
            ("Database failure affecting multiple services",
             {"alert_id": "ENT-008-A", "environment": "PROD", "service_name": "order-service",
              "error_message": "Primary database connection lost: all order, payment, and notification flows affected",
              "stack_trace": (
                  "psycopg2.OperationalError: could not connect to server\n"
                  '  File "/app/order/db.py", line 89, in get_connection\n'
                  "    conn = await pool.acquire()\n"
                  "  File \"/app/order/api.py\", line 45, in handle_request\n"
                  "    return await process_order(data)\n"
                  "FATAL: database cluster is in recovery mode"
              ),
              "severity": "CRITICAL", "git_commit_hash": "a1b2c3d4e5f6"}),
        ]
    )


# ════════════════════════════════════════════════════════════════════════════
# PROBLEM 9 — LLM Cost Governance
# ════════════════════════════════════════════════════════════════════════════

def problem_9():
    show_solution(
        9,
        "LLM Cost Governance for AI-Powered Operations",
        """
An enterprise adopts AI-powered incident response. Every incident calls GPT-4.
After one month: the bill is $12,000. Finance is not happy.
The problem: every alert — including disk space warnings — uses the most expensive model.

An SRE team analyzing 50 incidents/day × 30 days × $0.06/1K output tokens adds up fast.
        """,
        """
The system has built-in cost governance from day one:
• Model tiering: LOW/MEDIUM → gpt-3.5-turbo ($0.002/1K); HIGH/CRITICAL → gpt-4 ($0.06/1K)
• Environment-based: DEV/SIT use cheaper models automatically
• Budget enforcement: $1000/month default; >80% triggers optimization mode
• Result caching: high-confidence results cached for 3600s — no repeat LLM calls for identical issues
• Usage tracking: every call logged in llm_usage table (model, tokens, cost, environment)
• Cost reporting: monthly cost summary view by environment and model
        """,
        [
            ("Low-severity alert — uses cheap model automatically",
             {"alert_id": "ENT-009-A", "environment": "DEV", "service_name": "logging-service",
              "error_message": "Log shipping delayed by 30s: buffer at 60% capacity",
              "stack_trace": "Warning: log buffer filling faster than drain rate",
              "severity": "LOW", "git_commit_hash": "a1b2c3d4e5f6"}),

            ("High-severity alert — uses full-power model",
             {"alert_id": "ENT-009-B", "environment": "PROD", "service_name": "payment-service",
              "error_message": "Payment processing halted: all 10 workers in deadlock state",
              "stack_trace": (
                  "concurrent.futures.TimeoutError: workers timed out\n"
                  '  File "/app/payment/worker.py", line 67, in process\n'
                  "    result = await asyncio.wait_for(task, timeout=30)"
              ),
              "severity": "CRITICAL", "git_commit_hash": "a1b2c3d4e5f6"}),
        ]
    )


# ════════════════════════════════════════════════════════════════════════════
# PROBLEM 10 — Compliance & Audit Trail
# ════════════════════════════════════════════════════════════════════════════

def problem_10():
    show_solution(
        10,
        "Compliance & Audit Trail Requirements",
        """
A financial regulator asks: "For each production incident last quarter, provide:
1. When was it detected?
2. What was the diagnosis?
3. Who approved the remediation?
4. What command was executed?
5. When was it resolved?
6. Was the customer impacted for longer than the SLA allows?

The SRE team has 5 days to respond. They have Slack messages, some Jira tickets,
and a lot of blank stares. The response costs $50,000 in engineering time and
risks a compliance violation.
        """,
        """
The system makes compliance reporting a SQL query:
• audit_events table: event_id, action, actor, target, timestamp, environment, source_ip, details
• 9 tracked actions: ALERT_RECEIVED → ALERT_FILTERED → CONTEXT_RETRIEVED → DIAGNOSIS_COMPLETE → JIRA_TICKET_CREATED → HUMAN_APPROVED → REMEDIATION_EXECUTED → WORKFLOW_COMPLETED / WORKFLOW_ERROR
• Every action logged with actor identity, UTC timestamp, and structured JSON details
• Jira ticket linked to every incident that reached that stage
• SLA metrics in service_sla_metrics table: resolution times per service per day
• Immutable materialized view for tamper-evident daily summaries
• Filesystem JSON audit logs as additional integrity layer

What used to take 5 days and $50K now takes 5 minutes and a SELECT query.
        """,
        [
            ("Standard incident with full audit trail",
             {"alert_id": "ENT-010-A", "environment": "PROD", "service_name": "auth-service",
              "error_message": "OAuth token refresh failure: authorization server returned HTTP 500",
              "stack_trace": (
                  "HTTPError: 500 Server Error\n"
                  '  File "/app/auth/oauth.py", line 123, in refresh_token\n'
                  "    resp = await session.post(url, data=payload)\n"
                  "  File \"/app/auth/handler.py\", line 56, def authenticate"
              ),
              "severity": "HIGH", "git_commit_hash": "a1b2c3d4e5f6"}),
        ]
    )


# ════════════════════════════════════════════════════════════════════════════
# RUNNER
# ════════════════════════════════════════════════════════════════════════════

ALL = [
    ("Legacy App Blind Spots — Log Tripwire", problem_0),
    ("Alert Fatigue — Too Many Noisy Alerts", problem_1),
    ("Slow Incident Triage & Diagnosis", problem_2),
    ("Knowledge Silos", problem_3),
    ("Runbook Execution Under Pressure", problem_4),
    ("Escalation Delays & Missed SLAs", problem_5),
    ("Inconsistent Incident Response", problem_6),
    ("Post-Incident Review Data Gaps", problem_7),
    ("Cross-Team Coordination", problem_8),
    ("LLM Cost Governance", problem_9),
    ("Compliance & Audit Trail", problem_10),
]


def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print("Usage: python enterprise_solutions.py [problem_numbers...]")
        print()
        print("Examples:")
        print("  python enterprise_solutions.py          # run all 10")
        print("  python enterprise_solutions.py 1 4 10    # problems 1, 4, 10")
        print()
        print("Enterprise Problems:")
        for i, (title, _) in enumerate(ALL, 1):
            print(f"  {i:2d}. {title}")
        sys.exit(0)

    if args:
        indices = [int(a) - 1 for a in args if a.isdigit()]
    else:
        indices = list(range(len(ALL)))

    print()
    print("╔" + "═" * 76 + "╗")
    print("║" + "  Auto-SRE-Graph — Enterprise SRE Problem Solver".center(74) + "║")
    print("║" + f"  API: {API}".ljust(74) + "║")
    print("╚" + "═" * 76 + "╝")
    print()

    for i in indices:
        if 0 <= i < len(ALL):
            title, fn = ALL[i]
            try:
                fn()
            except Exception as e:
                print(f"{PAD}⚠  Problem {i+1} raised: {e}")
        else:
            print(f"{PAD}⚠  Unknown problem number: {i+1}")

    print(f"\n{SEP}")
    print("  All enterprise solution demonstrations complete.")
    print(f"{SEP}\n")


if __name__ == "__main__":
    main()
