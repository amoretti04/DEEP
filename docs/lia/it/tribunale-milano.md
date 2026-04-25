# Legitimate Interests Assessment — Tribunale di Milano — Sezione Fallimentare

**Source ID:** `it-tribunale-milano`
**Country:** IT
**Jurisdiction class:** (fill: eu_gdpr | eea_gdpr_adequacy | non_eu_separate_regime | global_case_by_case)
**Date:** (fill)
**Reviewer:** (fill — lawyer email)

---

## 1. Purpose

Describe why DIP is ingesting this source and what investment-intelligence
purpose it serves (CLAUDE.md §3.2 / PRD §19.1).

## 2. Necessity test

Is ingesting this source necessary to achieve the purpose? Are there
less-intrusive alternatives?

## 3. Balancing test

Data subjects' rights and freedoms vs. our legitimate interest.
Document which categories of data are present, whether any are
`personal_sensitive`, and what minimization applies.

## 4. Lawful basis

Default: Art. 6(1)(f) GDPR legitimate interests. For UK sources, UK-GDPR.
For CH sources, FADP + GDPR adequacy. For UAE, PDPL. For KSA, PDPL-KSA.

## 5. Data minimization

List every personal / personal_sensitive field we capture and justify each.

## 6. Retention

Default: 24 months in the raw lake, longer in canonical for active
proceedings. Specific overrides for this source:

## 7. Data-subject rights

DSAR / erasure / objection workflow reference: `docs/runbooks/dsar.md`

## 8. Verdict

* **Approved:** date + reviewer sign-off → update Source Card
  `legal_review.verdict: approved` and fill `date` + `reviewer`.
* **Rejected:** record the reason here; connector must never be
  enabled.

