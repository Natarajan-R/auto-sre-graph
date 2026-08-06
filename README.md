# Auto-SRE-Graph

Companion code for the book **Enterprise AI Workflow Automation: Building
Resilient Agentic Systems**.

📖 **Get it on Amazon Kindle:** [US](https://www.amazon.com/dp/B0HCZC7VCC) · [India](https://www.amazon.in/dp/B0HCZC7VCC)

An autonomous SRE diagnostic engine: it intercepts deployment failures, reasons
about root cause with real context, pauses for human approval, and executes
remediation behind an allowlist. The book builds it one layer at a time; this
repository is the finished reference implementation.

## What it does

A pipeline failure arrives as a webhook. The engine validates it against a
strict contract, drops it if it is noise, retrieves both semantic history
(Qdrant) and dependency topology (Neo4j), asks an LLM for a structured
diagnosis, and then **stops** — writing its entire state to PostgreSQL and
waiting, for as long as it takes, for an engineer to approve the fix in Jira.
Approval wakes the workflow, which executes the remediation under an allowlist
and a hard timeout.

A pattern mining subsystem reads the accumulated history and turns it into
something proactive: clusters of recurring errors, velocity trends, cascade
roots, and a forecast of which failure is most likely to page you next.

## Architecture at a glance

| Layer | Module | Role |
|---|---|---|
| Ingress | `src/api` | FastAPI webhooks, rate limiting, Pydantic contracts |
| Orchestration | `src/orchestrator` | LangGraph state machine, PostgreSQL checkpointing, circuit breakers, deduplication |
| Reasoning | `src/agents` | pydantic-ai diagnostic agent with enforced output schema |
| Context | `src/context` | Vector RAG (Qdrant) + GraphRAG (Neo4j) |
| Execution | `src/tools`, `src/integrations` | allowlisted remediation, Jira and ADO clients |
| Mining | `src/mining` | clustering, velocity, cascade roots, forecasting, runbook matching |
| Observability | `src/observability` | OpenTelemetry tracing, audit log, SLA and cost tracking |

## Getting started

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements/requirements.txt
cp .env.example .env          # fill in your keys
docker compose -f docker/docker-compose.yml up -d
pytest                        # 287 tests, no external services required
```

The demo scripts run standalone with no infrastructure:

```bash
python mining_demo.py            # clustering, velocity and cascade analysis
python mining_demo_phase2.py     # persistence, scheduling, notifications
python mining_demo_phase3.py     # forecasting and risk scoring
```

## CI/CD

The pipelines from Chapter 11 are in [`ci-cd/`](ci-cd/) — lint, the test suite
against ephemeral Postgres, Neo4j and Qdrant containers, image build and Trivy
scanning, then a gated deploy. They are **reference files that do not run**:
GitHub Actions executes only what lives in `.github/workflows/`, so nothing here
triggers on a push or expects a secret. [`ci-cd/README.md`](ci-cd/README.md)
covers how to activate them.

## Reading this alongside the book

Code listings in the book carry a header naming the file they came from:

```python
# src/orchestrator/graph.py
```

Listings are **excerpts** — trimmed to the lines that carry the point, so
imports, logging and defensive branches are often elided. Two markers appear
where the relationship needs saying out loud:

- `(simplified — the repo's version differs)` — a teaching version of code that
  genuinely exists here. Configuration lookups become literals and error
  handling is stripped so the idea fits in a dozen lines.
- `(extension — not in the companion repo)` — a capability the architecture
  invites but this implementation does not ship. Implementable from what the
  chapter teaches, and a good first exercise.

A header with neither marker is a faithful excerpt: shorter than the original,
but nothing in it was changed.

## Known limitations

Worth knowing before you rely on any of it:

- **Cost figures are reference values, not billing figures.** The price table in
  `src/observability/cost_manager.py` is not kept current. Check the provider's
  published pricing and update it before trusting any number it reports; a model
  missing from the table logs a warning and falls back to an unrelated rate.
- **Model identifiers age.** `src/config/settings.py` pins specific models. Verify
  them against current vendor documentation rather than assuming.
- **Pydantic v1 validators remain in `src/models/schemas.py`.** The book teaches
  v2 `@field_validator`, which is the direction this code is moving; the
  deprecation warnings in the test run point the same way. Where the two differ,
  the book is correct.
- This is a reference implementation written to be read. Review, test and harden
  it before pointing it at anything you care about — it executes shell commands.

---

## More books by the author

Each one is a hands-on build with its code in the open.

| Book | Amazon | Code |
|---|---|---|
| **Building a Local AI Coding Agent** | [US](https://www.amazon.com/dp/B0H8B6QXXX) · [IN](https://www.amazon.in/dp/B0H8B6QXXX) | [local-ai-coding-agent](https://github.com/Natarajan-R/local-ai-coding-agent) |
| **Agentic AI — A Hands-On Guide** | [US](https://www.amazon.com/dp/B0H6R7SZZB) · [IN](https://www.amazon.in/dp/B0H6R7SZZB) | [agentic-ai-book](https://github.com/Natarajan-R/agentic-ai-book) |
| **GraphRAG: Building an Intelligent Research Assistant with Knowledge Graphs** | [US](https://www.amazon.com/dp/B0H3QXVSY4) · [IN](https://www.amazon.in/dp/B0H3QXVSY4) | [graphrag-book-code](https://github.com/Natarajan-R/graphrag-book-code) |

All titles → [Amazon author page](https://www.amazon.com/stores/author/B0H3T2MG83)

---

## License

MIT — see [LICENSE](LICENSE).
