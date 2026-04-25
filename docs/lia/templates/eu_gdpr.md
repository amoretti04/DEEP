# LIA — EU-GDPR jurisdiction

**Source:** (fill source_id)
**Country:** (fill)
**Date:** (fill)
**Reviewer:** (fill — lawyer email)
**Verdict:** pending → approved / rejected

---

## 1. Controller & Processor roles

DIP operates as **controller** for analyst-facing derived data
(opportunities, watchlists, scoring). DIP acts as a **secondary
processor** of statutorily-published information (e.g. insolvency
administrator names in gazette notices).

## 2. Purpose

Investment intelligence on distressed corporate situations in the EU,
for the purpose of origination and diligence decisions by professional
investors. Specific to this source:

(fill)

## 3. Necessity test

Is ingesting this source necessary? Could we achieve the purpose with
less-personal data? Document.

(fill)

## 4. Balancing test (Art. 6(1)(f))

Weigh the rights of data subjects against our legitimate interest.
Relevant factors:
* Expectation — data is already published by a statutory authority for
  public interest purposes; data subjects have a *diminished* expectation
  of privacy for that specific fact.
* Sensitivity — names of administrators, debtors-as-natural-persons.
  Flag `personal`. Never `personal_sensitive`.
* Safeguards — minimization at extraction, 24-month raw retention,
  DSAR workflow, EU hosting.

(fill)

## 5. Categories of data captured

| Field | Personal? | Sensitive? | Justification | Retention |
|---|---|---|---|---|
| debtor_name (legal entity) | no | no | required | 24mo raw / active proceeding canonical |
| administrator_name | yes | no | required to link across filings | 24mo |
| (add rows as needed) | | | | |

## 6. Data-subject rights

Data subjects can exercise Art. 15 (access), 16 (rectification), 17
(erasure), 21 (object) via `dsar@<company>`. Workflow:
`docs/runbooks/dsar.md`. Suppressions propagate to canonical, search,
and UI with audit log, within the GDPR 30-day SLA.

## 7. Cross-border transfers

EU hosting (Frankfurt + Dublin). No transfers outside EU/EEA for
personal data without SCCs.

## 8. Sign-off

* **Date:**
* **Reviewer:** (lawyer email)
* **Verdict:** approved / rejected
* **Conditions:** (any)
* **Review cadence:** annual

Once approved, update the Source Card:

```yaml
legal_review:
  verdict: approved
  date: YYYY-MM-DD
  reviewer: name@example.com
  lia_path: docs/lia/<country>/<slug>.md
  notes: <any conditions>
```

...and then the connector is permitted to run.
