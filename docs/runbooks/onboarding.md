# Runbook — Onboarding a new source

This is the canonical procedure for adding a new source to DIP. The
scaffolding step produces files; the review and LIA steps produce the
**authorization** to run the connector in production.

## TL;DR

```bash
# 1. Scaffold
python -m scripts.onboard_source it/tribunale-milano \
    --name "Tribunale di Milano — Sezione Fallimentare" \
    --tier 1 --category COURT

# 2. Fill the LIA
$EDITOR docs/lia/it/tribunale-milano.md

# 3. Capture canary fixtures
#    Save 2–3 real detail pages to tests/canary/it/tribunale-milano/
#    Write expected canonical JSON alongside each.

# 4. Implement the parser
$EDITOR services/extract/parsers/it/tribunale-milano.py

# 5. Validate + test
make sources-validate
make test

# 6. PR. Include: ToS excerpt, robots.txt excerpt, page screenshot.
```

## Step-by-step

### 1. Scaffold

`scripts/onboard_source.py <country>/<slug>` creates four files and never
overwrites. If the slug exists, the script refuses — choose a different
slug or edit the existing files.

### 2. Fill the LIA

A Legitimate Interests Assessment is mandatory per CLAUDE.md §3.2 and
PRD §19.1. The template in `docs/lia/<country>/<slug>.md` walks through
the purpose, necessity, balancing, and retention tests. Counsel signs
off by adding their email + date to the Source Card's `legal_review`
block and flipping `verdict` to `approved`.

**Until that's done, the scheduler refuses to run the connector.** This
is a hard-coded check in `services/ingest/core/base.py::_assert_runnable`
and a regression test in `services/ingest/tests/test_connector.py`.

### 3. Capture canary fixtures

2–3 real raw payloads + expected canonical outputs, checked into
`tests/canary/<country>/<slug>/`. These become the regression suite:
any parser change that alters canary output fails CI. See
`tests/canary/<country>/<slug>/README.md` (the onboarding script created
it).

Before committing the raw HTML/PDF, scrub any personal data that isn't
needed to validate the parser — this is belt-and-braces for GDPR.

### 4. Implement the parser

`services/extract/parsers/<country>/<slug>.py` has a stub. Fill
`parse()`. Emit a list of extracted records matching the contract
documented in the parser file. The normalizer handles the mapping to
`Proceeding` + `ProceedingEvent` canonical models.

Parser semver (`__version__` in the module):
* patch — bug fix that preserves canary outputs
* minor — new field extracted; canary outputs change but are supersets
* major — structural change to the output contract; run replay (§5)

### 5. Validate + test

```bash
make sources-validate   # Source Card JSON-schema check
make test               # full unit suite incl. canary
```

### 6. Open a PR

Include in the PR description:

* **Source summary** — what it is, where it is, why it matters.
* **ToS excerpt** — the clause that permits (or doesn't forbid) automated
  access.
* **robots.txt excerpt** — for the paths you're scraping.
* **Screenshot** of a detail page + link to the captured canary.
* **LIA sign-off** — link to the signed LIA.

## Red lines (never do)

* Never enable a source without an approved LIA.
* Never commit raw data with identifiable personal information beyond
  what's strictly required for the regression tests.
* Never use a CAPTCHA solver.
* Never override `respect_robots: false` without a recorded legal sign-off.
* Never lower `politeness` below the §7.4 PRD defaults without
  justification in the Source Card.

## Replay (after parser version bumps)

```bash
# Re-parse the last 90 days of raw data with the new parser version.
python -m scripts.replay --source-id it-tribunale-milano --since 90d
```

`replay.py` is scheduled automatically on a parser minor/major bump (see
CLAUDE.md §10 and `infra/prefect/`), but you can invoke it manually for
targeted reprocessing.
