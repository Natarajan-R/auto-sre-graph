# Auto-SRE-Graph Architecture

## Diagram 1 — System Context (C4 Level 1)

```mermaid
C4Context
  title System Context — Auto-SRE-Graph

  Person(devops, "DevOps Engineer", "Triggers alerts, approves remediation")
  Person(sre, "SRE Team", "Reviews escalated incidents")
  Person(eng, "Engineering Manager", "Reviews system health reports")

  System_Boundary(sre_system, "Auto-SRE-Graph") {
    System(tripwire, "Log Tripwire", "Sidecar daemon — tails logs, filters errors, dispatches alerts")
    System(api, "API Gateway", "FastAPI — ingress for alerts, webhooks & mining queries")
    System(workflow, "Workflow Engine", "LangGraph DAG — orchestration with PostgreSQL checkpointing")
    System(agents, "AI Agents", "pydantic-ai — LLM-based diagnosis & analysis")
    System(context, "Context Retrieval", "Vector search (Qdrant) + Graph topology (Neo4j)")
    System(integrations, "Integrations", "Jira, ADO, Webhooks, Remediation shell")
    System(mining, "Pattern Mining", "Clustering, velocity detection, cascade analysis, health reports")
    System(observability, "Observability", "OTel tracing, audit logging, cost mgmt, SLA monitor")
  }

  System_Ext(ado, "Azure DevOps", "Pipeline alerts & run info")
  System_Ext(jira_ext, "Jira", "Ticketing & escalation")
  System_Ext(llm, "LLM Providers", "OpenAI / Anthropic / LiteLLM")
  System_Ext(slack, "Slack", "Notifications")
  System_Ext(legacy_app, "Legacy Applications", "Raw log files — no webhooks, no APM")

  Rel(devops, api, "POST /webhooks/ado", "JSON alert payload")
  Rel(devops, api, "POST /webhooks/jira", "Approval callback")
  Rel(sre, jira_ext, "Reviews & approves tickets")
  Rel(eng, api, "GET /mining/report", "System health reports")
  Rel(api, workflow, "Background task start")
  Rel(workflow, agents, "Analyze alert + context")
  Rel(workflow, context, "Retrieve similar incidents & dependencies")
  Rel(workflow, integrations, "Create tickets, execute commands")
  Rel(workflow, observability, "Emit spans, metrics, audit events")
  Rel(ado, api, "Pipeline failure webhook")
  Rel(agents, llm, "LLM inference calls")
  Rel(integrations, jira_ext, "REST API")
  Rel(legacy_app, tripwire, "Reads log files", "/var/log/shared/*.log")
  Rel(tripwire, api, "POST /webhooks/tripwire", "Structured alert payload")
  Rel(api, mining, "GET /mining/*", "Cluster / patterns / report queries")
  Rel(mining, workflow, "Reads historical states", "PostgreSQL checkpoints")
  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

---

## Diagram 2 — Container Deployment (Docker Compose)

```mermaid
C4Container
  title Container Deployment — 10 Docker Services

  System_Boundary(docker, "Docker Compose — auto-sre-graph-network") {
    Container(tripwire, "Log Tripwire", "Python / aiohttp", "Sidecar — tails logs, filters, dispatches alerts — no ports")
    Container(api, "API Server", "Python / Uvicorn", "uvicorn src.api.webhooks:app — 4 workers, port 8000")
    Container(mining, "Mining Engine", "Python (in-process)", "Clustering, patterns, reports — runs inside API workers")
    ContainerDb(postgres, "PostgreSQL + pgvector", "pgvector/pgvector:pg15", "LangGraph checkpoints, incidents, audit, SLA, cost, dedup, embedding cache")
    ContainerDb(neo4j, "Neo4j Enterprise", "neo4j:5-enterprise", "Service dependency graph, topology queries")
    ContainerDb(qdrant, "Qdrant", "qdrant/qdrant:v1.7.0", "Vector store — runbook similarity search")
    ContainerDb(redis, "Redis", "redis:7-alpine", "Alert deduplication (5-min TTL)")
    Container(litellm, "LiteLLM Gateway", "ghcr.io/berriai/litellm", "Multi-provider LLM proxy — port 4000")
    Container(otel, "OTel Collector", "otel/opentelemetry-collector-contrib", "Trace aggregation & export — ports 4318/4317")
    Container(pgadmin, "pgAdmin", "dpage/pgadmin4", "DB admin UI — port 5050")
  }

  Rel(tripwire, api, "POST /webhooks/tripwire", "Structured alerts (HTTP port 8000)")
  Rel(api, postgres, "psycopg async pool", "SQL (port 5432)")
  Rel(api, neo4j, "neo4j async driver", "Bolt (port 7687)")
  Rel(api, qdrant, "qdrant-client async", "gRPC/REST (port 6333)")
  Rel(api, redis, "redis async", "TCP (port 6379)")
  Rel(api, litellm, "HTTP / pydantic-ai", "LLM routing (port 4000)")
  Rel(api, otel, "OTLP HTTP exporter", "Spans & metrics (port 4318)")
  Rel(api, mining, "In-process calls", "/mining/clusters, /patterns, /report")
  Rel(mining, postgres, "Reads workflow states", "checkpoint_blobs table")
  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

---

## Diagram 3 — Workflow State Machine (LangGraph DAG)

```mermaid
stateDiagram-v2
  [*] --> START : Ingest alert
  START --> retrieve_context : edge

  state retrieve_context {
    [*] --> query_qdrant : VectorRAG.search_similar()
    [*] --> query_neo4j : GraphRAG.get_service_topology()
    query_qdrant --> append_context : Merge results
    query_neo4j --> append_context
    append_context --> [*]
  }

  retrieve_context --> diagnostic_agent : edge

  state diagnostic_agent {
    [*] --> canary_check : 10% experiment routing
    canary_check --> cost_optimize : Select model tier
    cost_optimize --> llm_inference : pydantic-ai Agent.run()
    llm_inference --> fallback_model : On failure
    fallback_model --> static_fallback : On repeated failure
    llm_inference --> output : DiagnosticAnalysis
    fallback_model --> output
    static_fallback --> output
    output --> [*]
  }

  diagnostic_agent --> routing : _route_post_diagnosis()

  state routing <<fork>>
  routing --> create_jira_ticket : proposed_action != ESCALATE_ONLY && error_count < 3
  routing --> escalate_only : proposed_action == ESCALATE_ONLY
  routing --> handle_error : error_count >= 3 || analysis == None

  state create_jira_ticket {
    [*] --> jira_api : Create ticket (circuit breaker)
    jira_api --> wait_human : Ticket created → pause
    wait_human --> resume : POST /webhooks/jira
    resume --> check_approved
    check_approved --> execute_remediation : approved == true
    check_approved --> skip_remediation : approved == false
    skip_remediation --> [*]
  }

  state execute_remediation {
    [*] --> validate : Allowlist check & timeout
    validate --> run : subprocess
    run --> success
    run --> failure
    success --> [*]
    failure --> [*]
  }

  execute_remediation --> [*] : COMPLETED
  escalate_only --> [*] : ESCALATED
  handle_error --> [*] : ERROR
```

---

## Diagram 4 — Data Flow (End-to-End)

```mermaid
sequenceDiagram
  participant Ext as External (ADO / Custom)
  participant App as Legacy App
  participant Trip as Tripwire
  participant API as FastAPI
  participant Val as Validation
  participant Wf as SREWorkflow
  participant Qd as Qdrant
  participant Ng as Neo4j
  participant LLM as LiteLLM
  participant Jr as Jira
  participant DB as PostgreSQL
  participant Mining as Mining Engine
  participant Obs as Observability
  participant Eng as Engineering Mgr

  Ext->>API: POST /webhooks/ado (PipelineAlert)
  API->>Val: API key / JWT / rate limit
  Val-->>API: OK
  API->>Val: Pydantic validation + redaction
  Val-->>API: Validated payload
  API->>Wf: background_tasks.add_task(start_workflow)

  Note over API: Response sent: {"status":"processing"}

  App-->>App: Writes log file
  Trip->>App: Reads /var/log/shared/*.log
  Note over Trip: Regex match? <br/> Debounce check? <br/> Buffer stack trace?
  Trip->>API: POST /webhooks/tripwire (structured alert)
  API->>Val: Validate + dedup
  API->>Wf: background_tasks.add_task(start_workflow)

  Wf->>DB: _initialize_pool() → AsyncConnectionPool
  Wf->>DB: _get_checkpointer() → setup() / migrations
  Wf->>Obs: Audit: ALERT_RECEIVED

  Wf->>Wf: Deduplication (Redis SHA-256 check)

  Wf->>Qd: VectorRAG.search_similar(alert) — circuit breaker
  Qd-->>Wf: Top 5 runbooks (vector_context)
  Wf->>Ng: GraphRAG.get_service_topology(service) — circuit breaker
  Ng-->>Wf: Dependency graph (graph_topology)
  Wf->>Obs: Audit: CONTEXT_RETRIEVED

  Wf->>LLM: DiagnosticAgent.analyze(alert + context)
  LLM-->>Wf: DiagnosticAnalysis (structured)
  Wf->>Obs: Audit: DIAGNOSIS_COMPLETE

  alt ESCALATE_ONLY
    Wf->>Jr: Jira.create_escalation_ticket()
    Jr-->>Wf: Ticket ID
    Wf->>Obs: Audit: JIRA_TICKET_CREATED
    Wf->>Obs: Metrics: ESCALATED
  else confidence > threshold
    Wf->>Jr: Jira.create_ticket() + pause for HITL
    Jr-->>Wf: Ticket ID
    Wf->>Obs: Audit: JIRA_TICKET_CREATED

    Ext->>API: POST /webhooks/jira (approval)
    API->>Wf: resume_workflow(thread_id, approved=true)
    Wf->>DB: aget_state() → load from checkpoint
    Wf->>Obs: Audit: HUMAN_APPROVED

    Wf->>Wf: RemediationTool.execute() — subprocess
    alt success
      Wf->>Obs: Audit: REMEDIATION_EXECUTED + WORKFLOW_COMPLETED
    else failure
      Wf->>Obs: Audit: WORKFLOW_ERROR
    end
  else error_count >= 3
    Wf->>Wf: handle_error node
    Wf->>Obs: Audit: WORKFLOW_ERROR
  end

  Note over DB: Event data accumulates over days/weeks

  Eng->>API: GET /mining/report?days=30
  API->>Mining: generate_report()
  Mining->>DB: SELECT checkpoint_blobs WHERE created_at > cutoff
  DB-->>Mining: 1000s of workflow states
  Mining->>Mining: ClusterEngine.cluster_events()
  Mining->>Mining: PatternDetector.analyze_clusters()
  alt LLM key available
    Mining->>LLM: GPT-4o-mini summarization
    LLM-->>Mining: Enhanced health report
  end
  Mining-->>API: Markdown health report
  API-->>Eng: {"report": "..."}
```

---

## Diagram 5 — Component Architecture (Layered)

```mermaid
flowchart TB
  subgraph API_Layer["API Layer (src/api)"]
    Webhooks["webhooks.py<br/>FastAPI app<br/>5 endpoints"]
    Deps["dependencies.py<br/>Security / RateLimit / Validation"]
  end

  subgraph Orchestrator["Orchestration Layer (src/orchestrator)"]
    Graph["graph.py<br/>SREWorkflow<br/>LangGraph DAG"]
    State["state.py<br/>SREWorkflowState TypedDict"]
    Checkpointer["checkpointer.py<br/>AsyncPostgresSaver<br/>Pool Manager"]
    Dedup["deduplication.py<br/>AlertDeduplicator"]
    Recovery["recovery.py<br/>CircuitBreaker / Retry"]
    Canary["canary.py<br/>A-B Experiments"]
  end

  subgraph Agents["Agent Layer (src/agents)"]
    Diagnostician["diagnostician.py<br/>pydantic-ai Agent"]
    Prompts["prompts.py<br/>SRE System Prompt"]
  end

  subgraph Context["Context Layer (src/context)"]
    VectorRAG["vector_rag.py<br/>Qdrant client"]
    GraphRAG["graph_rag.py<br/>Neo4j client"]
    Embeddings["embeddings.py<br/>OpenAI / Cohere / HF"]
  end

  subgraph Integrations["Integration Layer (src/integrations)"]
    Jira["jira.py<br/>Jira REST API"]
    ADO["ado.py<br/>Azure DevOps API"]
    WebhookHandler["webhook_handler.py<br/>Generic processor"]
  end

  subgraph Tripwire["Log Ingestion (src/tools)"]
    TripwireDaemon["tripwire.py<br/>TripwireDaemon<br/>DebounceCapacitor"]
  end

  subgraph Mining["Mining Layer (src/mining)"]
    ClusterEngine["cluster_engine.py<br/>Token/Embedding clustering"]
    PatternDet["pattern_detector.py<br/>Velocity + cascade analysis"]
    ReportGen["report_generator.py<br/>LLM + rule-based reports"]
    EventStore["event_store.py<br/>PostgreSQL queries"]
  end

  subgraph Tools["Tools Layer (src/tools)"]
    Remediation["remediation.py<br/>Allowlisted subprocess"]
  end

  subgraph Observability["Observability (src/observability)"]
    Tracing["tracing.py<br/>OTel + MetricsCollector"]
    Audit["audit.py<br/>9 action types"]
    Cost["cost_manager.py<br/>LLM cost tracking"]
    SLA["sla_monitor.py<br/>Service levels"]
    Logging["logging.py<br/>Structured JSON"]
  end

  subgraph Models["Model Layer (src/models)"]
    Schemas["schemas.py<br/>PipelineAlert,<br/>DiagnosticAnalysis,<br/>JiraTicketDraft"]
    Validators["validators.py<br/>WebhookValidation,<br/>AlertFilter"]
  end

  subgraph Config["Configuration (src/config)"]
    Settings["settings.py<br/>70+ env vars"]
    Constants["constants.py<br/>Enums & defaults"]
  end

  Webhooks --> Deps
  Webhooks --> Graph
  Graph --> State
  Graph --> Checkpointer
  Graph --> Dedup
  Graph --> Recovery
  Graph --> Canary
  Graph --> Diagnostician
  Graph --> VectorRAG
  Graph --> GraphRAG
  Graph --> Jira
  Graph --> Remediation
  Graph --> Tracing
  Graph --> Audit
  Graph --> Cost
  Graph --> SLA
  Diagnostician --> Prompts
  Diagnostician --> Embeddings
  Jira --> WebhookHandler
  VectorRAG --> Embeddings
  Graph --> Settings
  Graph --> Schemas
  Graph --> Validators
  Webhooks --> TripwireDaemon
  ApiMining["/mining routes"] --> ClusterEngine
  ApiMining --> PatternDet
  ApiMining --> ReportGen
  ApiMining --> EventStore
  EventStore --> Graph
  ClusterEngine --> Embeddings
```

---

## Diagram 6 — Database Schema (Entity-Relationship)

```mermaid
erDiagram
  CHECKPOINTS ||--o{ CHECKPOINT_WRITES : ""
  WORKFLOWS ||--o{ WORKFLOW_EVENTS : ""
  INCIDENTS ||--o{ SERVICE_SLA_METRICS : ""

  CHECKPOINTS {
    text thread_id PK
    text checkpoint_ns PK
    text checkpoint_id PK
    text parent_checkpoint_id
    text type
    jsonb checkpoint
    jsonb metadata
  }

  CHECKPOINT_WRITES {
    text thread_id PK
    text checkpoint_ns PK
    text checkpoint_id PK
    text task_id PK
    int idx PK
    text channel
    text type
    bytea blob
  }

  WORKFLOWS {
    uuid id PK
    text thread_id UK
    text alert_id
    text service_name
    text environment
    text status
    text jira_ticket_id
    timestamp started_at
    timestamp completed_at
    jsonb metadata
    int error_count
    text[] error_messages
  }

  WORKFLOW_EVENTS {
    uuid id PK
    uuid workflow_id FK
    text thread_id
    text event_type
    text node_name
    jsonb event_data
  }

  INCIDENTS {
    uuid id PK
    text incident_id UK
    text alert_id
    text service_name
    text environment
    text severity
    text error_message
    text root_cause_summary
    numeric confidence_score
    text proposed_action
    int resolution_time_seconds
    text jira_ticket_id
    text status
  }

  AUDIT_EVENTS {
    uuid id PK
    text event_id UK
    text action
    text actor
    text target
    timestamp timestamp
    text environment
    text source_ip
    jsonb details
  }

  SERVICE_SLA_METRICS {
    uuid id PK
    text service_name UK
    text environment UK
    date metric_date UK
    int total_incidents
    int avg_resolution_time
    int p95_resolution_time
    int p99_resolution_time
    int rollback_count
    numeric success_rate
  }

  LLM_USAGE {
    uuid id PK
    text request_id
    text model
    int input_tokens
    int output_tokens
    numeric cost
    text environment
    text service_name
    text alert_id
  }

  ALERT_DEDUP {
    uuid id PK
    text fingerprint UK
    text alert_id
    text service_name
    text environment
    int occurrence_count
  }

  EMBEDDING_CACHE {
    uuid id PK
    text text_hash UK
    text text_preview
    vector embedding_vector
    text model
  }

  MINING_CLUSTERS {
    uuid id PK
    text cluster_name
    text error_type
    int event_count
    text representative_error
    text[] services_affected
    timestamp first_seen
    timestamp last_seen
    numeric velocity
    text trend
    int cascade_root_score
    jsonb metadata
  }

  MINING_EVENTS {
    uuid id PK
    uuid cluster_id FK
    text thread_id
    text alert_id
    text service_name
    text error_message
    text severity
    timestamp occurred_at
  }
```

---

## Diagram 7 — Observability Stack

```mermaid
flowchart LR
  subgraph App["Application"]
    Tracer["OpenTelemetry SDK<br/>@trace_span decorator"]
    Metrics["MetricsCollector<br/>In-memory counters"]
    AuditLogger["AuditLogger<br/>9 action types"]
    CostMgr["CostManager<br/>Budget: $1000/mo"]
    SLAMon["SLAMonitor<br/>p95/p99 resolution"]
    StructLog["LoggingManager<br/>JSON structured"]
  end

  subgraph Export["Exporters"]
    OTLP["OTLP HTTP Exporter<br/>port 4318"]
    Console["Console Exporter<br/>(DEV/SIT)"]
    AuditFile["Audit JSON File<br/>/var/log/..."]
    LogConsole["Console (stdout)"]
    LogFile["Rotating File<br/>10MB x 10"]
  end

  subgraph External["External Systems"]
    OTelCollector["otel-collector<br/>Batch processing"]
    LangSmith["LangSmith API<br/>(disabled in demo)"]
  end

  Tracer --> OTLP
  Tracer --> Console
  OTLP --> OTelCollector
  OTLP -.-> LangSmith
  AuditLogger --> AuditFile
  AuditLogger --> DB[(PostgreSQL<br/>audit_events)]
  StructLog --> LogConsole
  StructLog --> LogFile
  Metrics --> OTLP

  DB --> OTelCollector
```

---

## Diagram 8 — Kubernetes Deployment

```mermaid
flowchart TB
  subgraph K8s["Kubernetes Cluster"]
    subgraph Namespace["Namespace: auto-sre-graph"]
      Ingress["nginx Ingress<br/>TLS (cert-manager)"]
      Service["ClusterIP Service<br/>port 8000"]
      HPA["HPA<br/>CPU 70% / mem 80%<br/>req/s 100<br/>scale 2-10"]
      PDB["PodDisruptionBudget<br/>minAvailable: 1"]

      subgraph Pods["3 Replicas (Deployment)"]
        Pod1["Pod 1<br/>api:8000 + mining<br/>+ tripwire sidecar"]
        Pod2["Pod 2<br/>api:8000 + mining<br/>+ tripwire sidecar"]
        Pod3["Pod 3<br/>api:8000 + mining<br/>+ tripwire sidecar"]
      end

      subgraph TripwirePods["Sidecar Container (per Pod)"]
        TW1["tripwire<br/>reads /var/log/shared/*.log<br/>POST /webhooks/tripwire"]
      end

      ConfigMap["ConfigMap<br/>105 env vars"]
      Secrets["Secrets<br/>DB, API keys"]
      CronJob["CronJob<br/>mining-report<br/>daily 08:00 UTC<br/>emails report"]
    end

    subgraph ExternalSvcs["External Services"]
      DB[(PostgreSQL<br/>pgvector)]
      Neo[(Neo4j)]
      Qd[(Qdrant)]
      Rd[(Redis)]
      LLM_GW[("LiteLLM<br/>port 4000")]
      OTel[("OTel Collector<br/>port 4318")]
    end
  end

  Client["Client / Load Balancer"] --> Ingress
  Ingress --> Service
  Service --> Pod1
  Service --> Pod2
  Service --> Pod3
  HPA --- Pods
  PDB --- Pods
  Pod1 --> ConfigMap
  Pod1 --> Secrets
  Pod1 --> DB
  Pod1 --> Neo
  Pod1 --> Qd
  Pod1 --> Rd
  Pod1 --> LLM_GW
  Pod1 --> OTel
  Pod1 -.-> TripwirePods
  TW1 --> DB
  CronJob --> DB
  CronJob --- Pods
```

---

## Diagram 9 — Error & Resilience Patterns

```mermaid
flowchart LR
  subgraph CircuitBreaker["Circuit Breaker Pattern"]
    CLOSED -->|"5 failures"| OPEN
    OPEN -->|"60s timeout"| HALF_OPEN
    HALF_OPEN -->|"3 successes"| CLOSED
    HALF_OPEN -->|"1 failure"| OPEN
  end

  subgraph Retry["Exponential Backoff + Jitter"]
    Attempt1["Retry 1<br/>delay: 2s"]
    Attempt2["Retry 2<br/>delay: 4s±20%"]
    Attempt3["Retry 3<br/>delay: 8s±20%"]
    Attempt1 --> Attempt2
    Attempt2 --> Attempt3
  end

  subgraph Fallback["Cascading Fallback"]
    Primary["LLM Provider<br/>(Anthropic)"]
    Secondary["LLM Provider<br/>(OpenAI)"]
    Static["Hardcoded Fallback<br/>confidence: 0.3<br/>ESCALATE_ONLY"]
    Primary -->|failure| Secondary
    Secondary -->|failure| Static
  end

  CircuitBreaker --> Retry
  Retry --> Fallback
```
