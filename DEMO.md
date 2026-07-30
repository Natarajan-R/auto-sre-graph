# Auto-SRE-Graph Demo Guide

## Prerequisites

- Docker & Docker Compose
- API keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` (set in `.env` or export before starting).
  Without valid keys the workflow still runs end-to-end but the AI diagnosis and Jira escalation
  steps will record errors in the workflow state.

## 1. Start the full stack

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

This spins up: API server (`:8000`), PostgreSQL, Neo4j (`:7474`), Qdrant (`:6333`),
Redis (`:6379`), LiteLLM (`:4000`), OpenTelemetry collector, and pgAdmin (`:5050`).

## 2. Verify health

```bash
curl http://localhost:8000/health
# {"status":"healthy","environment":"DEV","version":"1.0.0",...}
```

## 3. Ingest an alert (triggers the AI workflow)

```bash
curl -X POST http://localhost:8000/webhooks/ado \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "alert_id": "DEMO-001",
    "environment": "SIT",
    "service_name": "auth-service",
    "error_message": "Connection timeout to database: Connection refused",
    "stack_trace": "Traceback: Connection refused at /app/auth/service.py:45",
    "severity": "HIGH",
    "git_commit_hash": "abc1234"
  }'
# {"status":"processing","alert_id":"DEMO-001","message":"Alert queued for processing"}
```

> **Note:** `git_commit_hash` must be at least 7 characters long.

## 4. Check workflow status

```bash
curl http://localhost:8000/status/DEMO-001
```

Example response (with valid API keys):

```json
{
  "thread_id": "DEMO-001",
  "status": "WAITING_ON_HUMAN",
  "jira_ticket_id": "SRE-42",
  "human_approved": false,
  "last_updated": "2026-07-30T08:30:00.123456",
  "state": { ... }
}
```

Possible statuses: `WAITING_ON_HUMAN`, `REMIDIATION_QUEUED`, `RESOLVED`,
`ESCALATED`, `ESCALATION_FAILED`, `COMPLETED`.

With demo/dummy API keys the workflow will still run but record errors in the
state (e.g. `ESCALATION_FAILED` with the error details in `error_messages`).

## 5. View metrics

```bash
curl http://localhost:8000/metrics
```

## End-to-end workflow

1. **Receives** the alert via `POST /webhooks/ado`
2. **Validates & deduplicates** it
3. **Retrieves context** from Neo4j (past incidents) and Qdrant (similar alerts via vector embeddings)
4. **AI diagnoses** via LiteLLM/OpenAI — determines severity, root cause, remediation plan
5. **Routes** — high-confidence actionable fixes → Jira ticket → pause for human approval;
   low-confidence → escalate
6. **Human approves** via `POST /webhooks/jira` with `{"thread_id":"DEMO-001","approved":true}`
7. **Remediation executes** — the proposed action (restart, rollback, scale-up, config change)

The workflow uses async PostgreSQL checkpointing via LangGraph's `AsyncPostgresSaver`,
so state persists across restarts.

## What to expect with demo keys

The workflow runs the full DAG regardless of external service availability.
Errors are caught per-node and collected in the final state:

| Service | Failure mode |
|---------|-------------|
| OpenAI | 401 — invalid API key → analysis falls back to a static message |
| Jira | 404 — dummy URL → escalation recorded as `ESCALATION_FAILED` |
| LangSmith | 403 — disabled in `.env` (`LANGCHAIN_TRACING_V2=false`) |
| Qdrant | Version mismatch warning (client 1.18 vs server 1.7) — harmless |

## 6. Pattern Mining Engine — Standalone Demos (No Docker)

All three demos run on the host machine with zero external dependencies.
Each demo exercises the corresponding phase's production code directly.

### Phase 1 — Mining Core

```bash
# Full pipeline: clustering → patterns → report
python mining_demo.py

# Individual stages
python mining_demo.py clusters    # clustering only
python mining_demo.py patterns    # velocity + cascade analysis
python mining_demo.py report      # system health report
```

**Expected output:** 31 seeded events clustered into pattern families
(Connection/Timeout, Authentication/Authorization, DNS, Memory, Connection Refused)
with velocity trends, cascade roots, and a markdown health report.

### Phase 2 — Production Hardening

```bash
# Full pipeline: snapshots → scheduler → notifier → metrics
python mining_demo_phase2.py

# Individual stages
python mining_demo_phase2.py snapshots    # persistence + cross-period diff
python mining_demo_phase2.py scheduler    # asyncio background loop lifecycle
python mining_demo_phase2.py notifier     # webhook dispatch logic
python mining_demo_phase2.py metrics      # Grafana-style aggregation
python mining_demo_phase2.py pipeline     # full scheduler mining run simulation
```

**Expected output:** Three hourly cluster snapshots saved and loaded,
scheduler start/stop lifecycle verified, notifications recorded,
aggregate metrics computed (all in-memory, no PostgreSQL required).

### Phase 3 — Predictive

```bash
# Full pipeline: forecast → risk → runbook → end-to-end
python mining_demo_phase3.py

# Individual stages
python mining_demo_phase3.py forecast     # SES vs DES comparison
python mining_demo_phase3.py risk         # page-risk score ranking
python mining_demo_phase3.py runbook      # runbook suggestion for 5 novel errors
python mining_demo_phase3.py pipeline     # end-to-end: forecast → risk → match
```

**Expected output:** Time-series forecasts for 4 error clusters
(Connection/Timeout rising, Memory emerging, Auth stable, DNS declining),
ranked page-risk scores with component breakdown, and runbook matches
for novel error messages.

## 7. Pattern Mining API (Against Running Stack)

With the full stack running (`docker compose -f docker/docker-compose.yml up -d`):

```bash
# Phase 1 — Core mining endpoints
curl http://localhost:8000/mining/clusters?days=7
curl http://localhost:8000/mining/clusters/0/events?limit=10
curl http://localhost:8000/mining/patterns?days=7
curl http://localhost:8000/mining/report?days=7
curl http://localhost:8000/mining/timeline?days=7\&granularity=day
curl http://localhost:8000/mining/services?days=7

# Phase 2 — Production hardening endpoints
curl http://localhost:8000/mining/metrics
curl http://localhost:8000/mining/snapshots?limit=10
curl -X POST http://localhost:8000/mining/run

# Phase 3 — Predictive endpoints
curl http://localhost:8000/mining/predictions?hours=24\&top_n=5
curl http://localhost:8000/mining/predictions/0
curl http://localhost:8000/mining/runbooks
curl -X POST http://localhost:8000/mining/runbook-suggestion \
  -H "Content-Type: application/json" \
  -d '{"error_message": "Connection timeout to database: refused after 30s on endpoint db-primary:5432"}'
```

## 8. Running the Mining Tests

```bash
# Unit tests for all three phases
python -m pytest tests/unit/test_mining.py tests/unit/test_mining_phase2.py tests/unit/test_mining_phase3.py -v

# Expected: 111 passed (34 + 31 + 46)
```

## 9. Tripwire Sidecar — Log Ingestion

The Tripwire sidecar runs automatically in the Docker stack as the
`tripwire` service. To test with custom log data:

```bash
# Write sample error lines to the shared volume
echo "[ERROR] 2026-07-30 Connection timeout to database at db-primary:5432" \
  >> /var/log/shared/application.log

# Tripwire picks up the line (match regex default: ERROR|CRITICAL|FATAL),
# fingerprints it, debounces, and POSTs to /webhooks/tripwire
# Check the API logs:
docker logs auto-sre-graph-api --tail 20
```

## Configuration

- All settings in `.env` at the project root
- `scripts/seed_data.py` pre-populates sample data for a richer demo
- `scripts/setup_db.sh` runs database migrations
