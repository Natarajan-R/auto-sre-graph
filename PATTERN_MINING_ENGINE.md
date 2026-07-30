# Pattern Mining Engine — Turning Legacy Logs into Actionable Intelligence

## Executive Summary

The tripwire ingests raw logs as individual events. The Pattern Mining Engine
clusters, analyzes, and summarizes those events to reveal the systemic issues
hidden in your legacy applications. It answers three questions:

1. **What keeps breaking?** — Cluster similar errors into pattern families
2. **What breaks together?** — Find temporal correlations and cascade roots
3. **What will break next?** — Detect accelerating error velocity

## Architecture Overview

```
┌──────────────┐    ┌──────────────┐    ┌─────────────────────┐
│  Tripwire     │───▶│  SRE Graph   │───▶│  PostgreSQL         │
│  (log tailer) │    │  API         │    │  (workflow states)  │
└──────────────┘    └──────────────┘    └──────────┬──────────┘
                                                   │
                                                   ▼
┌────────────────────────────────────────────────────────────────┐
│                    Pattern Mining Engine                        │
│                                                                │
│  ┌─────────────────┐  ┌────────────────┐  ┌────────────────┐  │
│  │ Event Store      │  │ Cluster Engine │  │ Pattern        │  │
│  │ (query PG)       │──│ (HDBSCAN +     │──│ Detector       │  │
│  │                  │  │  embeddings)   │  │ (temporal +    │  │
│  │                  │  │                │  │  cascade)      │  │
│  └─────────────────┘  └────────────────┘  └───────┬────────┘  │
│                                                     │          │
│                    ┌────────────────────────────────┘          │
│                    ▼                                           │
│  ┌──────────────────────────────────────────────────────┐     │
│  │  Report Generator (LLM summarization of clusters)    │     │
│  └──────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────────┐
│  API Endpoints:  GET /mining/clusters                          │
│                  GET /mining/patterns                          │
│                  GET /mining/report                            │
│                  GET /mining/timeline                          │
└────────────────────────────────────────────────────────────────┘
```

## Data Pipeline

### Step 1: Event Collection (Already Built)
- Tripwire reads logs → dispatches alerts → SRE Graph API processes → PostgreSQL stores state
- Each workflow state contains: `alert` (error_message, service_name, environment, timestamp, stack_trace), `analysis` (root_cause_summary, confidence_score), timestamps

### Step 2: Event Vectorization (New)
- Error messages are converted to embeddings using the existing `EmbeddingProvider`
- Each event stored alongside: alert_id, timestamp, service, error_message, embedding vector (1536d), cluster_id (assigned), is_cascade_root (boolean)

### Step 3: Clustering (New)
- **HDBSCAN** (Hierarchical Density-Based Spatial Clustering) groups embeddings
- Unlike K-means, HDBSCAN: needs no cluster count, handles noise (outliers), finds arbitrary shapes
- Parameters: `min_cluster_size=5`, `min_samples=3`, `metric=cosine`
- Output: each event gets cluster_id (-1 for noise/novel errors)

### Step 4: Pattern Detection (New)
- **Per-cluster temporal analysis**: count/hour, day-over-day change, weekday vs weekend
- **Velocity detection**: linear regression slope on daily counts — positive slope = accelerating
- **Cascade root detection**: when errors from cluster A precede cluster B within a window, mark A as upstream
- **Co-occurrence matrix**: which clusters fire together within N minutes

### Step 5: Report Generation (New)
- LLM receives: top N clusters by volume, velocity leaders, cascade roots, novel errors
- Generates: executive summary, systemic issues list, recommended actions

## Core Mining Techniques

### 1. Embedding-Based Clustering

```
Error: "Connection timeout to database: Connection refused after 30s"
Error: "DB connection timeout: psycopg2.OperationalError connection refused"
Error: "Cannot connect to PostgreSQL: timeout waiting for connection"
     → All map to same embedding cluster → "Database Connection Failures"
```

**Why embeddings over regex:** Regex needs rules written in advance. Embeddings
capture semantic similarity — "connection refused" and "cannot connect" cluster
together even if they share no common substrings.

### 2. Temporal Velocity Detection

Each cluster's daily event count is tracked. A simple linear regression over
the last N days determines if the error is accelerating:

```
velocity = slope of (day_index, event_count)
if velocity > threshold:  ⚠  Accelerating — needs investigation
if velocity < -threshold: ✅  Resolving (or being fixed)
if |velocity| < threshold: →  Stable chronic issue
```

### 3. Cascade Root Analysis

When errors from cluster A consistently appear 1-5 minutes before errors from
cluster B, cluster A is likely the root cause:

```
Cluster A: "DB connection timeout"      ← ROOT (appears first)
Cluster B: "HTTP 502 from payment-api"  ← CASCADE (5 min later)
Cluster C: "Payment processing failed"  ← CASCADE (8 min later)
```

### 4. Novel Error Detection

Events that don't fit any existing cluster (HDBSCAN labels them -1) are flagged
as novel errors. If the same novel error appears repeatedly, it graduates to a
new cluster — catching zero-day issues the regex pattern didn't anticipate.

## Enterprise Value Map

| Problem | Without Mining | With Mining |
|---------|---------------|-------------|
| Unknown app weaknesses | "We see errors but don't know top 5" | "Top 3 systemic issues: DB pool, DNS resolution, cert expiry" |
| Incident RCA | Manual investigation of each page | "83% of incidents trace to Cluster A — fix DB connection retry logic" |
| Capacity planning | Reactive scaling | "Payment errors accelerating 40% WoW — service needs attention" |
| Tech debt prioritization | Gut-feel decisions | "These 3 error clusters cost 120 engineer-hours/month" |
| On-call burnout | Every alert treated equally | New alert flagged "matches known cluster — 72% auto-resolve rate" |

## API Design

```
GET  /mining/clusters?days=7&min_size=5
  Returns: list of clusters with size, trend, top error, services affected

GET  /mining/clusters/{cluster_id}/events?limit=50
  Returns: raw events in the cluster

GET  /mining/patterns?days=14
  Returns: cascade roots, co-occurrence matrix, velocity leaders

GET  /mining/report?days=7&format=markdown
  Returns: LLM-generated health report (or rule-based if LLM unavailable)

GET  /mining/timeline?days=7&service=payment-service
  Returns: time-series event counts per cluster for charting

GET  /mining/metrics
  Returns: Grafana-friendly aggregate metrics (snapshots, clusters, velocity)

GET  /mining/snapshots?limit=20
  Returns: persisted cluster snapshots from the latest mining runs

POST /mining/run
  Triggers an immediate mining cycle (fetch → cluster → persist → notify)

**Phase 3 — Predictive:**
GET  /mining/predictions?hours=24&min_risk=0.0&top_n=10
  Returns: ranked page-risk scores for all clusters with forecast metadata

GET  /mining/predictions/{cluster_id}?days=7&method=double_exp
  Returns: 24h forecast + daily history for a single cluster

POST /mining/runbook-suggestion
  Body: {"error_message": "..."}
  Returns: top-K runbook matches with TF-IDF similarity scores

GET  /mining/runbooks?error_type=Memory
  Returns: all available runbooks, or a specific one by error type
```

## Forecasting Techniques

### 1. Simple Exponential Smoothing (SES)

```python
level_t = α * value_t + (1 - α) * level_{t-1}
forecast = level_T  (flat — same value for all future steps)
```

Used when trend is unreliable or data is sparse. α=0.3 default.

### 2. Double Exponential Smoothing (Holt's Method)

```python
level_t   = α * value_t + (1 - α) * (level_{t-1} + trend_{t-1})
trend_t   = β * (level_t - level_{t-1}) + (1 - β) * trend_{t-1}
forecast_k = level_T + k * trend_T
```

Adds a trend component (β=0.1) that captures growth or decay. Forecasts are
clamped at 0 to avoid negative event counts. Default method for all 24h
predictions.

### 3. Page Risk Score

A composite 0.0–1.0 score combining four signals:

| Signal | Weight | Notes |
|--------|--------|-------|
| Velocity | 25% | |velocity|/5, capped: how fast is the error growing |
| Cluster size | 25% | size/50, capped: how widespread is the error |
| Forecast peak | 20% | additive if peak > 1.3× current |
| Cascade count | 15% | additive if ≥3 cascades point to this root |
| Known cluster | 15% | known patterns scored higher than noise |

Labels: `critical ≥ 0.7`, `high ≥ 0.4`, `medium ≥ 0.2`, `low < 0.2`

### 4. Runbook Matching

TF-IDF token overlap between novel error messages and 10 built-in runbook
categories. Falls back to `_extract_error_type()` classification when no
token similarity exceeds threshold (>0.01). Runbooks cover: Connection/Timeout,
Connection Refused, Authentication/Authorization, Not Found, Memory,
Null Reference, DNS, Storage, CPU/Throttling, SSL/TLS.

## Testing & Demos

All three phases include standalone demos that run on the host with zero
external dependencies (no Docker, no PostgreSQL, no API keys). See
[DEMO.md](../DEMO.md#6-pattern-mining-engine--standalone-demos-no-docker)
for the full testing guide.

```bash
# Quick smoke test — all three phases
python mining_demo.py                  # Phase 1: 31 events → clusters → patterns → report
python mining_demo_phase2.py           # Phase 2: snapshots → scheduler → notifier → metrics
python mining_demo_phase3.py           # Phase 3: forecast → risk score → runbook match

# Unit tests — 111 total across all phases
python -m pytest tests/unit/test_mining.py tests/unit/test_mining_phase2.py tests/unit/test_mining_phase3.py -v
```

## Implementation Plan — All Phases

### Phase 1 — Mining Core
- `cluster_engine.py`: token-based + embedding clustering
- `pattern_detector.py`: temporal velocity, cascade roots, co-occurrence
- `report_generator.py`: LLM summary (with rule-based fallback)
- `event_store.py`: PostgreSQL query adapter for workflow states
- `api/mining.py`: REST endpoints
- `mining_demo.py`: complete demo with 31 seeded events

### Phase 2 — Production Hardening
- `persist.py`: PostgreSQL persistence for mining clusters and events
- `scheduler.py`: asyncio background periodic mining job
- `notifier.py`: webhook dispatch for new clusters, velocity spikes, cascade roots
- `migrations/002_add_mining_tables.sql`: MINING_CLUSTERS + MINING_EVENTS tables
- `api/mining.py`: added `/metrics`, `/snapshots`, `/run` endpoints
- `mining_demo_phase2.py`: cross-snapshot diff, scheduler lifecycle, notifications

### Phase 3 — Predictive
- `forecaster.py`: SES + DoubleES time-series forecasting, page risk scoring
- `predictor.py`: TF-IDF runbook matcher with 10 built-in runbooks
- `api/mining.py`: added `/predictions`, `/runbook-suggestion`, `/runbooks` endpoints
- `mining_demo_phase3.py`: forecast table, risk ranking, runbook suggestions
