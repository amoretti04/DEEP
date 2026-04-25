# ADR-0003 — Import all 906 sources, including non-EU (UAE, KSA, MENA, Global)

**Status:** Accepted
**Date:** 2026-04-21
**Deciders:** Product owner (explicit decision in session 0)
**Supersedes:** Aspects of CLAUDE.md §3.3 and PRD §3.2 that scope v1 to
              "IT, DE, FR, UK, ES, NL, CH, plus EU-level."

## Context

The blueprint workbook `Distressed_Investment_Sources_Implementation_
Blueprint.xlsx` contains 906 sources across 13 country/region buckets:

| Bucket | Count |
|---|---|
| Italy | 190 |
| Germany | 158 |
| France | 118 |
| Spain | 114 |
| Global | 76 |
| UK | 65 |
| Switzerland | 50 |
| Netherlands | 43 |
| UAE | 43 |
| KSA | 31 |
| EU | 8 |
| Europe | 7 |
| KSA/MENA | 3 |
| **Total** | **906** |

CLAUDE.md §3.3 scopes v1 to EU-7 + EU. The product owner decided in
session 0 to **import all 906 sources, treating the workbook as
authoritative**, overriding that scope constraint.

## Decision

1. **Import every row.** The blueprint importer persists all 906 sources
   into the `source` table with their original country, category, tier,
   and notes.
2. **Activation is gated by a per-source `legal_review` state.** No
   connector can run in production without `legal_review.verdict ==
   approved` in its Source Card. This gate is already specified in
   CLAUDE.md §9 and `sources/_schema.yaml`.
3. **Non-EU sources default to `legal_review.verdict: pending` with
   `jurisdiction_class` set based on the country.** The importer
   classifies each source into one of four jurisdiction_class values:
   - `eu_gdpr` — IT, DE, FR, UK (UK-GDPR), ES, NL, EU, Europe
   - `eea_gdpr_adequacy` — CH (Adequacy Decision)
   - `non_eu_separate_regime` — UAE (PDPL), KSA (PDPL-KSA), KSA/MENA
   - `global_case_by_case` — Global (e.g. D&B, Bloomberg, Moody's)
4. **Each `jurisdiction_class` requires a distinct LIA template** before
   any source under it can be approved. Templates live under
   `docs/lia/templates/`. EU-GDPR template ships in R1; non-EU templates
   are stubs to be filled with local counsel before activation.
5. **Scheduler enforces the gate.** Any source without an approved legal
   review is filtered out at the scheduler before jobs are created. This
   is covered by unit tests.

## Rationale

The product owner's call is honored, but engineering preserves the
compliance gate. The alternative — hard-filtering at import — would lose
information we may want to surface in the UI (analyst sees the source
exists but is not yet activated, with a clear reason).

The alternative of activating non-EU sources under the existing EU-GDPR
LIA template would be incorrect on the facts: UAE PDPL and KSA PDPL have
different lawful-basis structures, data-subject rights, and cross-border
transfer rules.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Non-EU sources accidentally enabled without jurisdiction-correct LIA | Scheduler test: `test_scheduler_rejects_unapproved_sources`. CI must be green. |
| Data hosted in EU may include UAE/KSA personal data — cross-border transfer risk | For non-EU sources with personal data, hosting tenancy decision deferred to DPO review in R7. Until then, non-EU sources are import-only (metadata), no fetch. |
| 906 sources overwhelm analyst triage | UI filters by `in_priority_scope` (EU-7 true by default) so analysts don't drown. |
| Workbook categories are inconsistent (200+ labels, many singletons) | Category normalization via `libs/taxonomy/source_category_map.yaml`; unmapped rows go to a review queue, never silently bucketed. |

## Consequences

- `libs/schemas/source.py::Source` gains `jurisdiction_class`, `legal_review`,
  `in_priority_scope` fields.
- `scripts/blueprint_import.py` computes `jurisdiction_class` from country.
- Scheduler tests must prove unapproved sources are skipped.
- R1 ships with `legal_review: pending` for every imported source except
  the 1–2 reference sources that have approved LIAs filed manually.

## Follow-ups (not in R1)

- Engage counsel on UAE PDPL and KSA PDPL LIA templates (R7).
- DPIA scope update (R4).
- UI badge for `in_priority_scope` vs. `in_broader_scope` (R2).

## Links

- CLAUDE.md §3.3, §9
- PRD §3.2, §19
- Source workbook: `Distressed_Investment_Sources_Implementation_Blueprint.xlsx`
