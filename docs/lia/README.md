# Legitimate Interests Assessments (LIAs)

Per CLAUDE.md §3.2 and PRD §19.1, every source that handles any data
(including metadata) about living natural persons needs an LIA. No
connector can run in production without a signed LIA — this is enforced
in `services/ingest/core/base.py::_assert_runnable`.

## Layout

```
docs/lia/
├── README.md                 # this file
├── templates/
│   ├── eu_gdpr.md            # default for IT/DE/FR/UK/ES/NL/EU
│   ├── eea_gdpr_adequacy.md  # CH (FADP + adequacy)
│   ├── non_eu_separate_regime.md  # UAE (PDPL), KSA (PDPL-KSA)
│   └── global_case_by_case.md     # Global vendors, case-by-case
├── <country>/
│   └── <slug>.md             # filled LIA per source
```

The onboarding script (`scripts/onboard_source.py`) copies the right
template into `<country>/<slug>.md` and fills in the source_id /
jurisdiction fields.

## Jurisdiction classes and LIA routing (ADR-0003)

| Country | Jurisdiction class | Template |
|---|---|---|
| IT DE FR UK ES NL EU | `eu_gdpr` | `templates/eu_gdpr.md` |
| CH | `eea_gdpr_adequacy` | `templates/eea_gdpr_adequacy.md` |
| AE SA | `non_eu_separate_regime` | `templates/non_eu_separate_regime.md` |
| XX (Global) | `global_case_by_case` | `templates/global_case_by_case.md` |

The importer sets `jurisdiction_class` on every Source on import; a
connector with `jurisdiction_class` that mismatches the signed LIA's
jurisdiction is a bug — the legal PR that approves the LIA must match.

## Status dashboard

Query:

```sql
SELECT jurisdiction_class,
       legal_review->>'verdict' AS verdict,
       count(*)
FROM source
GROUP BY jurisdiction_class, verdict
ORDER BY jurisdiction_class, verdict;
```

Expectation after R1: every row has `verdict = pending` (except the
manually approved reference sources, if any). LIA PRs land source by
source through R1→R2.
