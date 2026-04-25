# ADR-0001 — Technology stack for v1

**Status:** Accepted
**Date:** 2026-04-21
**Deciders:** Product owner, lead engineering agent (Claude Code)
**Context:** First session of the DIP build.

## Context

CLAUDE.md §5 declared a locked stack. The agent secondary prompt suggested
slightly different defaults (Celery instead of Prefect, Elasticsearch-or-
OpenSearch, Docker Compose as the operational target). Both can't be true;
we need one canonical answer before writing connectors and migrations.

Additionally, the product owner confirmed in session 0 that they want the
**full CLAUDE.md §5 stack stood up now**, not a phased build that defers
Temporal, Kafka, EKS, and NLLB-200.

## Decision

CLAUDE.md §5 is the authoritative stack. We adopt all of it on day 1, with
the caveats noted below for pieces that cannot run locally.

| Layer | Choice | Justification |
|---|---|---|
| Backend language | Python 3.12 | NLP ecosystem, parser libraries, team fluency |
| API | FastAPI + uvicorn | First-class async, Pydantic-native, OpenAPI free |
| Schemas | Pydantic v2 | Validation at every boundary (§7.2 CLAUDE.md) |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic | Mature, typed `Mapped[...]`, autogen migrations |
| Canonical DB | Postgres 16 | Reliability, JSONB for semi-structured payloads |
| Cache / rate-limit | Redis 7 | Centralized per-domain token bucket (§7.4 PRD) |
| Raw lake | S3 (Minio locally) | Object-lock + lifecycle → Glacier at 90d (§22 PRD) |
| Search | OpenSearch 2.x | Language analyzers for it/de/fr/es/nl/en |
| Messaging | Kafka (KRaft) | Replay semantics for re-parse workflows |
| Orchestration | Prefect 3 | Python-native DAGs, good DX |
| Stateful workflows | Temporal 1.25 | Long-running multi-step (e.g. parser replay) |
| Scraping | httpx + tenacity + Playwright | Static + JS-rendered coverage |
| HTML parsing | selectolax + lxml | Performance; selectors in Source Card |
| PDF | pdfplumber + PyMuPDF | Digital + layout-aware extraction |
| OCR | Tesseract (Tier 3 only) | Scanned PDFs; cost-gated |
| Translation | NLLB-200 self-hosted (pluggable) | Cost control; managed LLM for edge cases |
| Observability | Prometheus + Grafana + Loki + OTEL | Open standards |
| Frontend | React + TypeScript + Tailwind + Vite | Team default |
| Infra | Terraform + Kubernetes (EKS) + ArgoCD | GitOps, reproducible |
| Secrets | Vault / SSM | Never in code; rotated ≤ 90 d |

## Caveats and phased adoption *of individual components* (not the stack)

Three components can't meaningfully run on a laptop; they ship as production
configuration but dev uses a local surrogate:

1. **EKS + ArgoCD** — Terraform under `infra/terraform/` and k8s manifests
   under `infra/k8s/`, but `make compose-up` gives you the full runtime
   locally on docker-compose.
2. **NLLB-200 full model** — 5–10 GB per container. Shipped as a swappable
   `TranslationBackend` interface with a `stub` default (echo + language tag)
   for R1. Real NLLB container is wired in R5 where multilingual becomes
   load-bearing.
3. **Temporal + Kafka** — both run in docker-compose locally and are
   bootstrapped by `make compose-up`. No code paths depend on them in R1
   beyond boilerplate clients; they are exercised starting R2 (replay) and
   R4 (pipeline fan-out).

## Consequences

- **Onboarding cost is higher than a minimal stack.** New engineers will
  face Temporal, Kafka, Prefect, OpenSearch concepts on day 1. Mitigated
  by `make compose-up` (one command), runbooks under `docs/runbooks/`, and
  keeping R1 code paths simple.
- **Local laptop resources** — the full compose stack needs roughly 6 GB
  RAM and 20 GB disk. Documented in README.
- **No rewrites to Celery/Elasticsearch.** Closed by this ADR.
- **Any future deviation requires a superseding ADR.**

## Alternatives considered and rejected

- **Celery + Redis only (simpler).** Rejected: no native replay, no stateful
  workflow primitives, no source-level isolation. Would force custom code
  where Temporal / Prefect give it free.
- **Elasticsearch instead of OpenSearch.** Rejected on license grounds
  (Elastic License 2.0 precludes certain SaaS redistribution; not a blocker
  today but the cost of switching later is higher than picking OpenSearch now).
- **Airflow instead of Prefect.** Viable alternative; Prefect wins on DX and
  dynamic workflow definition for per-source variation.

## Links

- CLAUDE.md §5 — locked stack
- PRD §23 — tech stack recommendation
- ADR-0002 — repo layout
- ADR-0003 — scope expansion beyond EU-7
