# ADR-0006 — R3 scope: 12 court-portal parsers + selector-verification workflow + normalizer

**Status:** Accepted
**Date:** 2026-04-21
**Deciders:** Product owner (session 7)

## Context

R2 shipped the parser framework plus 5 reference parsers (Tribunale di
Milano, Insolvenzbekanntmachungen, BODACC, BOE-PRC, Centraal
Insolventieregister). The R3 question was whether to invest in entity
resolution, opportunity scoring, or parser-coverage expansion. The
product owner chose **parser expansion, court-portal biased, 10-15
highest-priority sources**.

## Decision

R3 delivers **three things** forming one complete vertical slice:

1. **12 court-portal parsers** across IT (5), DE (4), FR (3):
   * IT: Roma, Napoli, Torino, Bologna, Firenze — thin subclasses of
     the Milano reference parser since Italian tribunali share a
     common DOM pattern.
   * DE: Amtsgericht Berlin-Charlottenburg, München, Hamburg, Frankfurt
     am Main — all publish via the federal Insolvenzbekanntmachungen
     portal; distinguished by ``court_name``.
   * FR: Tribunal de Commerce Paris, Lyon, Nanterre — Greffe-level
     detail pages, structurally similar to each other.

2. **Selector-verification workflow** — ``scripts/verify_selectors.py``
   takes a source_id + a captured HTML file, runs the parser, reports
   which fields extracted cleanly and which came up empty. Closes the
   loop between "I captured a page" and "parser is production-ready"
   with zero manual diff work.

3. **Normalizer** — ``services/normalize/`` — the missing link between
   parser output and the canonical DB. Turns a ``ParsedRecord`` into
   Company / Proceeding / ProceedingEvent / Document rows plus the
   field-level ``parsed_field`` provenance. Without this, R3's 12
   parsers can't actually produce DB rows; adding it promotes R3 from
   "12 more modules" to "complete vertical slice, end to end."

## What we explicitly did NOT do

**Synthetic canary fixtures for 12 new sources.** For R2's 5 reference
parsers, synthetic fixtures were defensible — the point was proving the
framework worked. Repeating that pattern 12 more times creates canary
tests that pass against fabricated selectors that may or may not match
the real page structure. That's technical debt masquerading as coverage.

Instead:
* Each new parser's YAML carries selector patterns based on observed
  patterns in the R2 reference parsers for the same family
  (Italian tribunali, German Amtsgerichte, French tribunaux de commerce).
* Each parser is marked ``status: unverified`` until a real page is
  captured and ``scripts/verify_selectors.py`` confirms the selectors.
* The connector scope gate (``services/ingest/core/base.py``) already
  refuses to run any source with ``enabled=false``, so no unverified
  parser can hit production traffic accidentally.

**Entity resolution across sources** (deferred to R4).
**Opportunity scoring and alerting** (deferred to R5).

## Workflow for promoting an unverified parser to production

1. Operator navigates to the source, captures a representative detail
   page as HTML (browser "Save As"), drops it into
   ``captures/<country>/<slug>/001_raw.html``.
2. Runs ``python -m scripts.verify_selectors <source_id>
   captures/<country>/<slug>/001_raw.html``. Output: pass/fail per
   required field + extracted values.
3. If any required field is empty, updates the selector in
   ``sources/<country>/<slug>.yaml`` and re-runs.
4. When all required fields extract cleanly, runs
   ``python -m scripts.promote_canary <source_id>`` which copies the
   capture to ``tests/canary/<country>/<slug>/001_raw.html`` and
   writes the expected output JSON. Canary regression lock established.
5. Flips the Source Card to ``status: verified`` and sets ``enabled: true``.

## Status convention

| Source Card field | Meaning | Connector runs? |
|---|---|---|
| ``status: verified`` + ``enabled: true`` + ``legal_review.verdict: approved`` | Fully promoted | Yes |
| ``status: unverified`` | Parser scaffolded, selectors are best-guess patterns | No (``enabled: false`` enforced) |
| Missing ``status`` | Legacy (R1/R2 reference parsers) — implicitly verified | Yes (if other gates pass) |

## Rollback

Every R3 addition is additive. Removing R3 amounts to reverting the
parsers + normalizer + verification script; existing R1/R2 tests
remain green because none of them depend on R3 state.

## Links

* `docs/runbooks/onboarding.md` — parser onboarding procedure
* `scripts/verify_selectors.py` — implementation
* `services/normalize/` — normalizer implementation
* ADR-0004 — approved-by-default (context for Source Card state machine)
