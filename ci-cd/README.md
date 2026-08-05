# CI/CD reference pipelines

These are the pipelines Chapter 11 describes, kept here as **reference files
that do not run**. GitHub Actions only executes workflows found in
`.github/workflows/`, so parked in this directory they are inert: pushing to
this repository triggers nothing, deploys nothing, and needs no secrets.

| File | What it does |
|---|---|
| `ci.yaml` | Lint (black, ruff, mypy, pylint, bandit), the pytest suite against ephemeral Postgres, Neo4j and Qdrant service containers, a Docker build, and Trivy image scanning. |
| `cd.yaml` | Builds and publishes an image to GHCR, then deploys to staging and — behind an environment gate — production. |

## Activating them in your own project

Copy the one you want into place and commit it:

```bash
mkdir -p .github/workflows
cp ci-cd/ci.yaml .github/workflows/ci.yaml
```

Then supply the secrets it expects, under **Settings → Secrets and variables →
Actions**. Any step whose secret is missing will fail:

- `ci.yaml` — `SNYK_TOKEN`, `OPENAI_API_KEY`, `JIRA_URL`, `JIRA_USERNAME`,
  `JIRA_API_TOKEN`, `SLACK_WEBHOOK_URL`, `SLACK_CHANNEL`
- `cd.yaml` — `STAGING_KUBECONFIG`, `PRODUCTION_KUBECONFIG`,
  `SLACK_WEBHOOK_URL`, `SLACK_CHANNEL` (`GITHUB_TOKEN` is provided for you)

Read `cd.yaml` before you enable it. It deploys to whatever cluster your
kubeconfig points at, and the version in this repository has had its automatic
push trigger removed on purpose — decide deliberately what should trigger a
deployment in your environment rather than inheriting the choice from a book.
