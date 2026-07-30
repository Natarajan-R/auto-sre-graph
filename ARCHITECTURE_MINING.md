# Pattern Mining Engine — Architecture (All Phases)

Covers the mining subsystem across all three implementation phases.
See `ARCHITECTURE.md` for the broader Auto-SRE-Graph system.

---

## Diagram 1 — Mining Engine Component Architecture

```mermaid
flowchart TB

  subgraph Phase1["Phase 1 — Mining Core"]
    EventStore["event_store.py<br/>MiningEventStore<br/>PG checkpoint_blobs query"]
    ClusterEngine["cluster_engine.py<br/>ClusterEngine<br/>EmbeddingClusterEngine"]
    PatternDet["pattern_detector.py<br/>PatternDetector<br/>velocity / cascade / co-occurrence"]
    ReportGen["report_generator.py<br/>ReportGenerator<br/>LLM + rule-based reports"]
  end

  subgraph Phase2["Phase 2 — Production Hardening"]
    Persist["persist.py<br/>MiningPersist<br/>save / load / metrics"]
    Scheduler["scheduler.py<br/>MiningScheduler<br/>asyncio background loop"]
    Notifier["notifier.py<br/>MiningNotifier<br/>webhook dispatch"]
    Migration["migrations/002_add_mining_tables.sql<br/>MINING_CLUSTERS<br/>MINING_EVENTS"]
  end

  subgraph Phase3["Phase 3 — Predictive"]
    Forecaster["forecaster.py<br/>ExponentialSmoother<br/>DoubleExponentialSmoother<br/>page risk scoring"]
    Predictor["predictor.py<br/>RunbookMatcher<br/>10 built-in runbooks"]
  end

  subgraph API["API Layer (src/api/mining.py)"]
    Endpoints["mining router<br/>14 REST endpoints"]
    SchedLifecycle["startup / shutdown hooks<br/>scheduler lifecycle"]
  end

  Phase1 --> Phase2
  Phase2 --> Phase3
  Phase1 ---> API
  Phase2 ---> API
  Phase3 ---> API
  Persist ---> Migration
  Notifier ---> Scheduler
  Forecaster ---> Persist
  Predictor ---> ClusterEngine
```

---

## Diagram 2 — End-to-End Mining Data Pipeline

```mermaid
flowchart LR
  Tripwire["Tripwire<br/>tails log files"] --> API["API /webhooks/tripwire"]
  API --> PG[("PostgreSQL<br/>checkpoint_blobs")]

  subgraph Mining["Pattern Mining Engine"]
    direction TB
    ES["event_store.py<br/>get_events()"]
    CE["cluster_engine.py<br/>cluster_events()"]
    PD["pattern_detector.py<br/>analyze_clusters()"]
    PS["persist.py<br/>save_cluster_snapshot()"]
    NF["notifier.py<br/>notify_*()"]
    FC["forecaster.py<br/>forecast_cluster()"]
    RB["predictor.py<br/>RunbookMatcher.suggest()"]
  end

  PG --> ES
  ES --> CE
  CE --> PD
  CE --> PS
  CE --> FC
  PD --> NF
  PD --> FC
  FC --> RB["page_risk_score()"]

  PS -->|"MINING_CLUSTERS"| PG
  NF -->|"POST webhooks"| Slack["Slack / PagerDuty"]

  subgraph Demo["Demo Scripts"]
    D1["mining_demo.py<br/>31 seeded events"]
    D2["mining_demo_phase2.py<br/>snapshots + scheduler + notifier"]
    D3["mining_demo_phase3.py<br/>forecasts + risk + runbook"]
  end

  CE --> D1
  PS --> D2
  FC --> D3
```

---

## Diagram 3 — Phase 2: Production Hardening Flow

```mermaid
sequenceDiagram
  participant API as API Server
  participant Sched as MiningScheduler
  participant ES as EventStore
  participant CE as ClusterEngine
  participant PD as PatternDetector
  participant PS as MiningPersist
  participant NF as MiningNotifier

  Note over API,Sched: Startup: scheduler registered
  API->>Sched: start()
  Sched->>Sched: create_task(_run_loop)

  loop Every N minutes
    Sched->>Sched: _run_scheduled_mining()
    Sched->>ES: get_events(days=7, limit=5000)
    ES-->>Sched: List[Dict]
    Sched->>CE: cluster_events(events)
    CE-->>Sched: clusters[ ]
    Sched->>PD: analyze_clusters(clusters, events)
    PD-->>Sched: patterns{velocity, cascade, co-occurrence}
    Sched->>PS: save_cluster_snapshot(clusters, period, start, end)
    PS-->>Sched: saved_count

    Sched->>PS: get_latest_snapshot_period()
    Sched->>PS: load_clusters(period=previous)
    Sched->>NF: notify_new_clusters(current, previous)
    Sched->>NF: notify_velocity_spikes(velocity_data)
    Sched->>NF: notify_cascade_root(root_clusters)
    NF->>NF: _dispatch(POST webhook_url)
    Sched->>Sched: update _mining_run_metrics
  end

  Note over API,Sched: Shutdown: scheduler stopped
  API->>Sched: stop()
  Sched->>Sched: cancel_task()
```

---

## Diagram 4 — Phase 3: Prediction Pipeline

```mermaid
flowchart LR
  subgraph Input["Input Sources"]
    H["Cluster history<br/>from persist layer<br/>(newest-first snapshots)"]
    C["Current cluster<br/>velocity + size + trend"]
    CM["Cascade map<br/>root → cascade_count"]
    E["Novel error message<br/>from tripwire alert"]
  end

  subgraph Forecast["1. Forecasting"]
    REV["Reverse to chronological"]
    SES["ExponentialSmoother<br/>α=0.3<br/>flat forecast"]
    DES["DoubleExponentialSmoother<br/>α=0.3, β=0.1<br/>trend-aware forecast"]
    COMP["Choose DES by default<br/>fall back to SES<br/>if data < 2 points"]
    FC["forecast output<br/>• 24h values<br/>• peak<br/>• avg<br/>• trend_direction"]
  end

  subgraph Risk["2. Page Risk Scoring"]
    VEL["Velocity component<br/>25% — |vel|/5"]
    SZ["Size component<br/>25% — size/50"]
    FPK["Forecast peak<br/>20% — if peak > 1.3× current"]
    CAS["Cascade component<br/>15% — if cascade_count ≥ 3"]
    KNW["Known cluster<br/>15% — known > noise"]
    SCORE["composite score<br/>0.0 - 1.0"]
    LABEL["label: critical ≥ 0.7<br/>high ≥ 0.4<br/>medium ≥ 0.2<br/>low < 0.2"]
  end

  subgraph Runbook["3. Runbook Matching"]
    TOK["Tokenize novel error"]
    EXTRACT["_extract_error_type() classification"]
    TFIDF["TF-IDF similarity<br/>vs 10 runbook types"]
    MERGE["Combine results<br/>extract_type fallback<br/>if TF-IDF < 0.01"]
    SUGGEST["top-K suggestions<br/>error_type + similarity + runbook"]
  end

  H --> REV
  REV --> SES
  REV --> DES
  SES --> COMP
  DES --> COMP
  COMP --> FC

  C --> VEL
  C --> SZ
  FC --> FPK
  CM --> CAS
  C --> KNW
  VEL --> SCORE
  SZ --> SCORE
  FPK --> SCORE
  CAS --> SCORE
  KNW --> SCORE
  SCORE --> LABEL

  E --> TOK
  E --> EXTRACT
  TOK --> TFIDF
  TFIDF --> MERGE
  EXTRACT --> MERGE
  MERGE --> SUGGEST
```

---

## Diagram 5 — Mining API Surface (All Phases)

```mermaid
flowchart LR
  subgraph Phase1API["Phase 1 — Core"]
    C1["GET /mining/clusters<br/>Query: days, min_size, service, use_embeddings<br/>→ clusters[ ]"]
    C2["GET /mining/clusters/{id}/events<br/>Query: limit<br/>→ events[ ]"]
    P1["GET /mining/patterns<br/>→ cascade_roots, co-occurrence, velocity"]
    R1["GET /mining/report<br/>Query: format=markdown<br/>→ LLM/rule-based report"]
    T1["GET /mining/timeline<br/>Query: granularity=hour|day<br/>→ event count time-series"]
    S1["GET /mining/services<br/>→ service × cluster impact matrix"]
  end

  subgraph Phase2API["Phase 2 — Hardening"]
    M1["GET /mining/metrics<br/>→ total_snapshots, clusters, velocity, scheduler status"]
    SN1["GET /mining/snapshots<br/>→ latest persisted clusters"]
    RU1["POST /mining/run<br/>→ trigger immediate mining cycle"]
  end

  subgraph Phase3API["Phase 3 — Predictive"]
    PR1["GET /mining/predictions<br/>Query: hours, min_risk, top_n<br/>→ ranked page-risk scores"]
    PR2["GET /mining/predictions/{id}<br/>→ 24h forecast + daily history"]
    RB1["POST /mining/runbook-suggestion<br/>Body: {error_message}<br/>→ top-K runbook matches"]
    RB2["GET /mining/runbooks<br/>Query: error_type<br/>→ list or lookup runbooks"]
  end

  Phase1API --> Phase2API
  Phase2API --> Phase3API
```

---

## Diagram 6 — Notification Decision Tree

```mermaid
flowchart TD
  START["Scheduled mining run complete"] --> CHECK_NEW{"New clusters vs<br/>previous snapshot?"}
  CHECK_NEW -->|"cluster_id not in previous<br/>AND not noise"| DISPATCH_NEW["dispatch: mining.new_cluster<br/>severity: warning<br/>title: 'New error cluster detected'"]
  CHECK_NEW -->|"no new clusters"| SKIP_NEW["skip"]

  START --> CHECK_VELOCITY{"Velocity ≥ threshold?<br/>(|velocity| ≥ 2.0<br/>AND trend == accelerating)"}
  CHECK_VELOCITY -->|"yes"| DISPATCH_VEL["dispatch: mining.velocity_spike<br/>severity: high<br/>title: 'Velocity spike: {type}'"]
  CHECK_VELOCITY -->|"no"| SKIP_VEL["skip"]

  START --> CHECK_CASCADE{"Cascade root found?<br/>(cascade_count ≥ 1)"}
  CHECK_CASCADE -->|"yes"| DISPATCH_CAS["dispatch: mining.cascade_root<br/>severity: info<br/>title: 'Cascade root identified'"]
  CHECK_CASCADE -->|"no"| SKIP_CAS["skip"]

  subgraph Dispatch["HTTP POST via aiohttp"]
    WEBHOOK["External webhook URL<br/>configurable<br/>timeout: 10s"]
    SUCCESS["200 OK → logged"]
    FAIL["4xx/5xx/timeout → warning logged"]
    WEBHOOK --> SUCCESS
    WEBHOOK --> FAIL
  end

  DISPATCH_NEW --> WEBHOOK
  DISPATCH_VEL --> WEBHOOK
  DISPATCH_CAS --> WEBHOOK
```

---

## Diagram 7 — Forecasting Model Selection

```mermaid
flowchart TD
  INPUT["Cluster history<br/>(newest-first sizes)"] --> REVERSE["Reverse to chronological"]
  REVERSE --> CHECK_LEN{"len(values) ≥ 2?"}
  CHECK_LEN -->|"no"| FLAT["Return flat forecast<br/>= last observed value"]
  CHECK_LEN -->|"yes"| METHOD{"Method param?"}
  METHOD -->|"simple"| SES["ExponentialSmoother<br/>α = 0.3"]
  METHOD -->|"double_exp (default)"| DES["DoubleExponentialSmoother<br/>α = 0.3, β = 0.1"]
  SES --> LEVEL["level = α·v + (1-α)·level"]
  DES --> LEVEL_TREND["level = α·v + (1-α)·(level+trend)<br/>trend = β·(Δlevel) + (1-β)·trend"]
  LEVEL --> FLAT_FC["forecast = level<sub>T</sub><br/>(same for all steps)"]
  LEVEL_TREND --> TREND_FC["forecast<sub>k</sub> = level<sub>T</sub> + k·trend<sub>T</sub><br/>clamped at ≥ 0"]
  FLAT_FC --> OUTPUT
  TREND_FC --> OUTPUT

  OUTPUT["Output:<br/>• 24 forecast values<br/>• peak<br/>• avg<br/>• trend_direction"]
  OUTPUT --> DIRECTION{"direction logic<br/>(last 3 obs avg vs<br/>first 8 forecast avg)"}
  DIRECTION -->|"fcst > 1.2× obs"| RISING["rising"]
  DIRECTION -->|"fcst < 0.8× obs"| FALLING["falling"]
  DIRECTION -->|"otherwise"| STABLE["stable"]
```

---

## Diagram 8 — Database Schema (Mining Tables)

```mermaid
erDiagram
  MINING_CLUSTERS ||--o{ MINING_EVENTS : "cluster_ref_id"

  MINING_CLUSTERS {
    uuid id PK
    int cluster_id UK "per-snapshot cluster number"
    text error_type "Connection/Timeout, Memory, etc."
    text representative_error "truncated to 500 chars"
    int size "number of events in cluster"
    text[] services "affected services"
    text[] severities "HIGH, CRITICAL, etc."
    timestamp first_seen
    timestamp last_seen
    bool is_noise "singleton cluster flag"
    text snapshot_period UK "YYYYMMDDHH identifier"
    timestamp snapshot_start
    timestamp snapshot_end
    real velocity "linear regression slope"
    text trend "accelerating | declining | stable"
    timestamp created_at
  }

  MINING_EVENTS {
    uuid id PK
    uuid cluster_ref_id FK "ON DELETE CASCADE"
    text thread_id
    text alert_id
    timestamp timestamp
    text service_name
    text environment
    text error_message "truncated to 2000 chars"
    text severity "HIGH default"
    text snapshot_period
    timestamp created_at
  }

  MINING_CLUSTERS ||--o{ MINING_CLUSTERS : "velocity_history via error_type"

  MINING_CLUSTERS {
    int idx_snapshot_period "IDX"
    int idx_velocity "IDX (DESC)"
    int idx_trend "IDX"
    int idx_services "GIN index"
  }

  MINING_EVENTS {
    int idx_timestamp "IDX (DESC)"
    int idx_service "IDX"
    int idx_snapshot "IDX"
    int idx_cluster_ref "IDX"
  }
```

---

## File Inventory by Phase

| Phase | File | Purpose |
|-------|------|---------|
| 1 | `src/mining/event_store.py` | Query PostgreSQL `checkpoint_blobs` for workflow states |
| 1 | `src/mining/cluster_engine.py` | TF-IDF token clustering + embedding clustering (fallback) |
| 1 | `src/mining/pattern_detector.py` | Velocity regression, cascade roots, co-occurrence, heatmap |
| 1 | `src/mining/report_generator.py` | LLM-enhanced reports (GPT-4o-mini) + rule-based fallback |
| 1 | `src/api/mining.py` | 6 core REST endpoints + `/metrics`, `/snapshots`, `/run` |
| 1 | `mining_demo.py` | 31 seeded events across 5 real-world clusters |
| 2 | `src/mining/persist.py` | PostgreSQL CRUD for `MINING_CLUSTERS` + `MINING_EVENTS` |
| 2 | `src/mining/scheduler.py` | `asyncio` background mining loop with configurable interval |
| 2 | `src/mining/notifier.py` | `aiohttp` webhook dispatch for new clusters, spikes, roots |
| 2 | `migrations/002_add_mining_tables.sql` | DDL for mining tables with GIN indexes |
| 2 | `mining_demo_phase2.py` | Cross-snapshot diff, scheduler lifecycle, notification log |
| 3 | `src/mining/forecaster.py` | SES + DoubleES forecasting, page risk scoring, cluster ranking |
| 3 | `src/mining/predictor.py` | TF-IDF runbook matcher with 10 built-in runbooks |
| 3 | `mining_demo_phase3.py` | Forecast table, risk ranking, runbook suggestions |
