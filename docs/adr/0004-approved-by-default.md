# ADR-0004 — Legal review "approved" by default during R2+

**Status:** Accepted
**Date:** 2026-04-21
**Deciders:** Product owner (session 3)
**Supersedes:** Aspects of ADR-0003 §4 and CLAUDE.md §3.2 defaults.
**Applies to:** R2 onward, until explicitly rolled back.

## Context

ADR-0003 set every imported source to `legal_review.verdict: pending` so
no connector could run until counsel signed off on a per-source LIA.
This is the safe default and aligns with CLAUDE.md §3.2 and PRD §19.1.

In session 3, the product owner directed that all imported sources
default to `approved` so R2 can proceed without the per-source legal
review workflow that would otherwise block parser bring-up.

## Decision

1. **`scripts/blueprint_import.py` sets `legal_review.verdict: approved`
   on import** for every source, with a system-identified reviewer
   (`reviewer: system-default@dip.local`) and a timestamp of the import.
2. **The scope gate in `services/ingest/core/base.py::_assert_runnable`
   remains unchanged.** It still refuses to run unless both `enabled`
   and `legal_review.verdict == approved`. This means `enabled=false`
   continues to block execution — activation is two-gated, not one.
3. **`enabled` stays `false` by default on import.** A source goes live
   only when the operator explicitly flips `enabled=true` (per source,
   via the scheduler config or `/v1/sources/{id}` admin endpoint in R3).
4. **LIA templates and the DSAR workflow are preserved.** They are not
   wired into activation blocking, but they continue to exist under
   `docs/lia/` and the GDPR data-minimization tagging in extraction is
   NOT relaxed.

## Rationale

The product owner has assessed that:
* Most sources in the workbook are statutorily public (gazettes, court
  portals, insolvency registers) where the legitimate-interest basis
  is well-established.
* The operational cost of per-source LIA review would delay the first
  usable version of the platform by months.
* A two-gated activation (`enabled` + `legal_review.verdict`) is still
  meaningful because `enabled` requires a conscious per-source flip.

Engineering's role is to preserve the technical controls that make a
later re-introduction of LIA throughput cheap, not to re-litigate the
policy call.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A non-EU source activates under EU-GDPR defaults | `jurisdiction_class` is still tracked per ADR-0003 and surfaced in the UI. Any source outside `eu_gdpr` carries a visible badge. |
| Data-subject rights workflow atrophies | DSAR runbook kept; suppression fields on every canonical model kept; UI "Request erasure" surfaces present from R6. |
| Audit trail of approvals is synthetic | Import writes `reviewer: system-default@dip.example` + `date: <import_ts>` + `notes: "ADR-0004 approved-by-default"`. The synthesis is explicit and greppable — not hidden as if counsel reviewed each source. |
| Regulatory inspection | The approved-by-default policy is documented, time-bounded to R2+ unless an ADR supersedes this one, and separable from technical controls (minimization, retention, suppression). |

## Rollback path

If this policy is rolled back (supersede via ADR-NNNN), the required
changes are narrow:

1. Flip the default in `scripts/blueprint_import.py::_build_legal_review()`
   from `approved` back to `pending`.
2. For existing sources in the DB, run:
   ```sql
   UPDATE source
   SET legal_review = jsonb_set(legal_review, '{verdict}', '"pending"')
   WHERE (legal_review->>'reviewer') = 'system-default@dip.example';
   ```
3. The scope gate requires no change (it was never relaxed).
4. Individual sources with real LIA sign-off keep their `approved`
   status because their `reviewer` field won't match
   `system-default@dip.local`.

The synthetic-approval marker is what makes a clean rollback possible.
Do not remove it without thinking about this case.

## What did NOT change

* `services/ingest/core/base.py::_assert_runnable` — still enforces
  `enabled AND approved`.
* Regression tests in `services/ingest/tests/test_connector.py` — still
  prove unapproved-AND-enabled sources refuse to run. Those tests use
  hand-constructed `Source` objects and are unaffected by the importer
  default change.
* GDPR data-minimization tags on extracted fields.
* DSAR / erasure suppression infrastructure.
* Every other guardrail in CLAUDE.md §3.

## Links

* ADR-0003 — jurisdiction_class and scope expansion
* CLAUDE.md §3.2, §3.3, §17 (Ask-first rules — this is one)
* `scripts/blueprint_import.py` — implementation
