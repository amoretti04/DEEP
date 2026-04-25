# Runbook — Incident response

Follow this for any P1/P2 incident.

## Severities

| Severity | Definition | Response time |
|---|---|---|
| P1 | Tier-1 freshness SLA breach (>4h) across 3+ sources, OR data loss suspected, OR legal/compliance breach suspected. | Page on-call. Ack ≤ 10 min. Mitigation ≤ 1h. |
| P2 | Single Tier-1 source down, OR DLQ growing, OR user-facing API degraded. | Page on-call. Ack ≤ 30 min. Mitigation ≤ 4h. |
| P3 | Tier-2/3 source issues, non-urgent data quality. | Slack. Fix next business day. |

## First 10 minutes

1. **Acknowledge** in PagerDuty. Post in `#dip-incidents` with the
   Grafana panel screenshot.
2. **Check** the source-health dashboard (Grafana).
3. **Circuit-breaker** — is it open? (`redis-cli keys 'dip:cb:*'`)
4. **Isolate** — is the issue one source or many? If many, check
   infrastructure (Postgres, Redis, Minio, OpenSearch) before parsers.
5. **Legal?** If the issue involves scraping behavior, personal data, or
   ToS changes, escalate to the DPO *immediately*. Don't "fix" it
   technically first.

## Common scenarios

### Source returns 429/403 for an extended period
* Check Source Card `politeness` — back off by 2×, redeploy.
* Check proxy pool health.
* If sustained, the source may be rate-limiting us specifically.
  Consider reaching out to the source owner (most public-register
  operators will whitelist legitimate research). Do **not** rotate User
  Agents to evade — that's a ToS red line.

### Parser regression on canary
* CI catches this pre-merge. If it reaches prod, something got shipped
  without running tests.
* Pin the previous parser version, open a revert PR.

### DLQ growing
* Read-only replay from DLQ into a dev env to reproduce.
* Classify: transient (network) → re-enqueue; deterministic (parser bug)
  → pin parser version, fix, ship, replay.

### Raw lake write failure
* Check Minio/S3 health.
* If cap-limit exceeded, check S3 lifecycle rules (should rotate to
  Glacier at 90d per CLAUDE.md §22).

### DSAR / Erasure request
* Follow `docs/runbooks/dsar.md` (TBD).
* The platform suppresses personal fields across canonical, search,
  and UI within SLA (≤ 30d per GDPR Art. 12).

## Communicate

* At ack: "I've got this, investigating, update in 15."
* At hypothesis: "Believe this is X; validating by Y."
* At mitigation: what happened, what changed, what's next.
* Post-incident: RCA doc within 5 business days per PRD §17.3.

## Tools

* Grafana: source health, pipeline throughput, data quality, freshness.
* Loki: structured logs (filter by `source_id`, `run_id`).
* Temporal UI: stateful workflow states (<http://localhost:8080>).
* Prefect UI: scheduler runs (<http://localhost:4200>).
* OpenSearch dashboards: search indexing health.

## Do not

* Do not silence a flaky source for more than a day without a linked issue.
* Do not clear the DLQ without a recovery plan.
* Do not push a parser change directly to prod without canaries passing.
* Do not lower a politeness setting under pressure to "catch up" after an
  outage. Catching up is a product concern; overwhelming the source is
  an ethics concern.
