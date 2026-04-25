# PRD — Distressed Investment Intelligence Platform

The authoritative PRD is maintained alongside this repo (the RTF file
committed at project bootstrap). This markdown copy is a placeholder;
replace with the full PRD text during the first docs PR.

Until then, read:

1. **`CLAUDE.md`** — operating manual (loaded every session, §17 ask-first rules)
2. **`docs/adr/0001-stack.md`** — locked tech stack + caveats
3. **`docs/adr/0002-repo-layout.md`** — repository layout
4. **`docs/adr/0003-scope-including-mena-global.md`** — scope expansion + jurisdiction_class gate
5. **`docs/runbooks/onboarding.md`** — how to add a source
6. **`docs/runbooks/incident.md`** — on-call procedure

## High-level product summary

DIP ingests, normalizes, enriches, and ranks distressed corporate
situations from ~900 public sources across Europe and adjacent markets.
Single power user + small analyst team. The edge comes from being early:
Tier-1 sources (gazettes, insolvency registers, tribunals) surface to
the analyst within ≤ 4h of publication.

### Scope

* **In:** corporate distress — gazettes, tribunals, registers,
  registries, credit bureaus, auctions tied to operating businesses,
  insolvency news, regulators.
* **Out of v1:** residential real-estate foreclosures, consumer
  bankruptcy without an operating entity, NPL tape workflows,
  predictive pre-filing distress modeling (v2), trading execution.

### Guardrails

* Every record carries a provenance envelope (source URL, raw artifact,
  hash, parser version, timestamp, legal basis).
* Every source carries a Source Card with explicit `legal_review`.
  Connectors refuse to run without `verdict: approved`.
* Personal data tagged at extraction; `personal_sensitive` never stored.
* Consumer insolvency filtered at the extractor.
* 24-month raw retention.
* EU hosting for personal data; SCCs otherwise.

### Release plan

Eight releases. R1 (this scaffold) is the foundation:

1. **R1 — MVP Foundation** ✅ (this delivery)
2. R2 — Parsing & Canonical Normalization (field-level provenance, OCR)
3. R3 — Entity Resolution & Case Linking
4. R4 — Opportunity Detection MVP (rule-based scoring, alerts)
5. R5 — Multilingual & Coverage Expansion (NLLB-200 translation)
6. R6 — Analyst Workflow & Search Operations
7. R7 — Production Hardening & Governance (RBAC, audit, DR)
8. R8 — Full Business-Ready Platform
