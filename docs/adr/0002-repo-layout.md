# ADR-0002 — Repository layout

**Status:** Accepted
**Date:** 2026-04-21
**Deciders:** Product owner, lead engineering agent

## Context

CLAUDE.md §6 specifies `services/` + `libs/` top-level directories. The
agent secondary prompt proposes `apps/` + `packages/`. Both are valid
conventions; picking one deterministically matters more than which.

## Decision

**CLAUDE.md §6 layout wins verbatim.** Rationale: CLAUDE.md is the
operating manual that reloads every session; diverging would create
recurring friction. The `services/` label is also more honest — each
sub-directory is an independently deployable service (FastAPI app, Prefect
worker, parser worker), not an "app" in the monorepo-app sense.

## Structure

```
dip/
├── CLAUDE.md
├── docs/
│   ├── PRD.md                  # source of truth
│   ├── adr/                    # this folder
│   ├── lia/                    # Legitimate Interests Assessments
│   ├── runbooks/               # on-call procedures
│   └── weekly/                 # weekly status notes
├── sources/                    # Source Card YAMLs, one per source
│   ├── _schema.yaml            # JSON-schema validator
│   ├── it/ de/ fr/ uk/ es/ nl/ ch/ eu/
├── services/
│   ├── ingest/
│   │   ├── core/               # base connector, rate limiter, raw lake
│   │   ├── connectors/         # concrete connector subclasses if needed
│   │   └── tests/
│   ├── extract/
│   │   ├── parsers/<country>/  # per-source parser modules, semver'd
│   │   ├── nlp/                # NER, event typing, translation
│   │   └── tests/
│   ├── normalize/              # entity resolution, dedup
│   ├── enrich/                 # financials, sector, ownership
│   ├── score/                  # rule-based v1
│   ├── api/                    # FastAPI serving
│   └── web/                    # React + TS frontend
├── libs/
│   ├── schemas/                # Pydantic v2 canonical models
│   ├── provenance/             # envelope, record_uid, PIDs
│   └── taxonomy/               # category + proceeding-type maps
├── infra/
│   ├── docker-compose.yaml
│   ├── alembic/                # migrations
│   ├── terraform/
│   ├── k8s/
│   └── prefect/                # Prefect deployments
├── scripts/
│   ├── blueprint_import.py     # import the xlsx
│   ├── onboard_source.py       # scaffold a new source
│   ├── validate_sources.py     # CI-time schema check
│   └── replay.py               # re-parse raw lake with new parser
├── tests/
│   ├── integration/
│   ├── canary/<country>/<slug>/
│   └── fixtures/
└── .github/workflows/
```

## Packaging

Single `pyproject.toml` at the root, with `libs/`, `services/`, `scripts/`
as importable top-level Python packages. Each sub-package has its own
`tests/` folder living next to the code (colocation makes moves cheaper
than a distant `tests/libs/schemas/...` mirror).

## Consequences

- Imports are `from libs.schemas import Company`, `from services.ingest.core
  import SourceConnector`, `from services.extract.parsers.it.tribunale_milano
  import parse`. Clear and grep-friendly.
- No confusion about where a new source goes — Source Card in
  `sources/<country>/<slug>.yaml`, parser in
  `services/extract/parsers/<country>/<slug>.py`, canary in
  `tests/canary/<country>/<slug>/`.
- Any deviation requires a superseding ADR.

## Alternatives considered and rejected

- `apps/` + `packages/` (second prompt): contradicts CLAUDE.md §6 which
  reloads every session; continually diverging prompt vs. filesystem would
  be a pit.
- Per-service `pyproject.toml` (Nx/Turborepo-style): overkill for a
  single-language monorepo; revisit if/when a service needs a different
  Python version or ships to a different registry.

## Links

- CLAUDE.md §6
- ADR-0001 stack
