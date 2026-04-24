# DIP — Distressed Investment Intelligence Platform

Automated intelligence platform that ingests, normalizes, enriches, and ranks
distressed corporate situations from ~900 public sources across Europe (IT,
DE, FR, UK, ES, NL, CH) and adjacent markets. Single-user + small analyst
team; full provenance, multi-lingual, deal-grade metadata.

**Source of truth:** `docs/PRD.md` (product) and `CLAUDE.md` (operating manual).
**ADRs:** `docs/adr/`. **LIAs:** `docs/lia/`. **Source Cards:** `sources/`.

## What's in this release

**R3** — Tier-1 parser expansion (12 court portals) + selector-verification workflow + normalizer.

| Component | Status |
|---|---|
| 906-row importer with URL-path-aware IDs (905 distinct sources) | ✅ (R1/R2) |
| Parser framework — `DeclarativeParser` (HTML) + `DeclarativeXmlBulkParser` (XML) | ✅ (R2) |
| Reference parsers: Tribunale di Milano, Insolvenzbekanntmachungen, BODACC, BOE-PRC, CIR | ✅ (R2) |
| Canary regression locks on all reference parsers | ✅ 24 tests (R2) |
| Field-level provenance on every extracted field | ✅ (R2) |
| Translation pipeline — on-demand NLLB-200, cached, per-user feature flag | ✅ (R2) |
| REST API: `/v1/proceedings/{pid}`, `/v1/documents/{pid}/translate`, `/v1/settings` | ✅ (R2) |
| Document viewer + Settings UI | ✅ (R2) |
| **12 additional court-portal parsers — IT(5), DE(4), FR(3)** | ✅ (R3) |
| **Shared base classes: `ItalianTribunaleParser`, `GreffeTribunalParser`** | ✅ (R3) |
| **`status: unverified` → `verified` Source Card state machine (ADR-0006)** | ✅ (R3) |
| **`scripts/verify_selectors.py` — selector verification CLI** | ✅ (R3) |
| **Normalizer — `ParsedRecord` → Company / Proceeding / Event / Document / ParsedField rows** | ✅ (R3) |
| **Cross-source linkage on (jurisdiction, court_case_number)** | ✅ (R3) |
| **Company resolution by codice_fiscale / SIREN / HRB / KvK / RSIN / NIF-CIF** | ✅ (R3) |
| **ADR-0006 (R3 scope and synthetic-canary policy)** | ✅ (R3) |

Remaining ~140 Tier-1 parsers: promotable with the verify-selectors workflow
once real pages are captured. Remaining: entity-resolution (probabilistic
matching, analyst merge/unmerge) is R4.

---

## Quickstart (local dev)

```bash
# 1. Python env
make dev                    # install deps + pre-commit hooks

# 2. Infra
make compose-up             # postgres, redis, minio, opensearch, kafka, temporal, prefect
cp .env.example .env

# 3. Schema
make migrate                # alembic upgrade head

# 4. Seed sources from the blueprint workbook
BLUEPRINT_FILE=Distressed_Investment_Sources_Implementation_Blueprint.xlsx \
    make blueprint-import

# 5. Run
make api                    # FastAPI on :8000
make web                    # React on :5173

# 6. (R2) Optional: real NLLB-200 model instead of the stub translation service.
#    Without this, `compose-up` already starts a stub that echoes text with a
#    clear "[stub xx→yy]" marker so you can exercise the full translation UX
#    end-to-end. For real translations, bring up the `nllb` profile too:
docker compose --profile nllb up translation-nllb
#    First start is slow (~2.4 GB model download + load).
#    Then enable translation per-user at Settings → Translation.
```

---

## Layout (see CLAUDE.md §6 for canonical reference)

```
dip/
├── CLAUDE.md                   # operating manual (loaded every session)
├── docs/                       # PRD, ADRs, LIAs, runbooks, weekly notes
├── sources/                    # per-source YAML Source Cards + JSON-schema
├── libs/                       # shared, no-external-deps packages
│   ├── schemas/                # Pydantic v2 canonical models
│   ├── provenance/             # envelope + PID helpers
│   └── taxonomy/               # unified category + proceeding-type maps
├── services/
│   ├── ingest/                 # connectors (API | Bulk | HTTP | Headless)
│   ├── extract/                # per-source parsers + NLP
│   ├── normalize/              # entity resolution, dedup
│   ├── enrich/                 # financials, sector, ownership
│   ├── score/                  # rule-based v1
│   ├── api/                    # FastAPI serving layer
│   └── web/                    # React + TS + Tailwind frontend
├── infra/                      # Terraform, k8s, Alembic, docker-compose
├── scripts/                    # onboard_source, blueprint_import, replay
└── tests/                      # integration, canary, fixtures
```

---

## Must-reads before you touch anything

1. **`CLAUDE.md` §3** — non-negotiable guardrails (scraping, GDPR, scope, secrets).
2. **`CLAUDE.md` §17** — ask-first vs. decide-autonomously rules.
3. **`docs/PRD.md` §18** — ethical scraping policy.
4. **`docs/adr/`** — every architectural decision we've already made.

## Policies in one paragraph

Every record carries a provenance envelope (§11 CLAUDE.md). Every source has
a Source Card (§9). Every connector respects `robots.txt` unless a legal review
is on file. Personal data is tagged at extraction; `personal_sensitive` is
never stored; consumer insolvency is excluded at the extractor. No scraping
goes live without `legal_review.verdict == approved` in the Source Card. No
commit contains secrets — pre-commit gitleaks will block you, and so will CI.

## Release plan

Eight releases (R1–R8) per the agent prompt. See `docs/adr/0001-stack.md`,
`docs/adr/0002-repo-layout.md`, `docs/adr/0003-scope-including-mena-global.md`
for the decisions that frame R1.
# DEEP
