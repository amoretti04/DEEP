# ADR-0005 — Translation: on-demand, cached, NLLB-200 behind a feature flag

**Status:** Accepted
**Date:** 2026-04-21
**Deciders:** Product owner (session 3)

## Context

PRD §8.4 and CLAUDE.md §5 spec self-hosted NLLB-200 for bulk translation
of multilingual source content to English. The original assumption was
background batch translation at ingest time: every extracted record gets
an English side-by-side before the analyst ever looks at it.

Product direction in session 3 overrode this: translation is **opt-in
per user in settings**, and only when the user asks for an English view
should we hit the model. The reasoning is a combination of cost
(unnecessary GPU time on records nobody reads), latency (ingestion
blocks on translation otherwise), and a preference to keep the original
as the first-class representation.

## Decision

**Three components, loosely coupled:**

1. **Translation service** — an HTTP service that takes
   `(text, source_language, target_language)` and returns
   `(translated_text, model_metadata)`. It is stateless from the caller's
   perspective; the cache lives in Postgres.

2. **Cache table** — `translation_cache` keyed by
   `(sha256(source_text), target_language)`. First lookup is a cache
   miss (service call + persist); subsequent lookups for identical text
   are instant. Deduplicates across records that happen to share source
   strings (very common for standard legal boilerplate in gazette
   notices).

3. **Feature flag** — `UserSettings.translation.enabled`. When off, the
   API never calls the service and the UI never shows a toggle. Off by
   default for new users. When on, the UI shows an "EN" toggle on any
   original-language document; clicking it triggers a
   `POST /v1/documents/{did}/translate` which hits the cache → falls
   through to the service → persists → returns.

**UX:** first click is slow (one model inference ≈ 1-3 s per paragraph);
subsequent views are instant. This is the explicit session-3 choice.

## NLLB-200 deployment

Per session-3 direction: **full NLLB container, behind a feature flag,
off by default**. The container runs in the compose stack under the
`translation` profile. In CI and in the default `compose-up`, the
service stays down.

* Image: `facebook/nllb-200-distilled-600M` wrapped in a minimal FastAPI.
  600M-parameter distilled model chosen over 1.3B/3.3B for CPU
  inference feasibility (a real deployment would use `nllb-200-1.3B` on
  GPU; the distilled variant is the "runs on a laptop" fallback).
* Feature flag at container level: compose profile `translation` must
  be explicitly activated (`docker compose --profile translation up`).
* Feature flag at app level: `UserSettings.translation.enabled=true` on
  the user. The API enforces both; either off and the service is not
  reached.
* Model files are large (~2.4 GB for 600M distilled). They are not
  committed to the repo; the container downloads on first start from
  Hugging Face's model hub. We check the license (NLLB is CC-BY-NC, so
  the deployed service must not be used for commercial use without a
  separate arrangement — flagged as a follow-up).

## Trade-offs

| Concern | Resolution |
|---|---|
| First-click latency | Accepted. Alternative (pre-translate at ingest) rejected per session-3. |
| Model license (CC-BY-NC) | Flagged. Action item: for commercial deployment, replace NLLB with a commercially-licensed alternative (Helsinki-NLP Opus-MT subset, or managed LLM with explicit license clearance). |
| Cost of GPU | Deferred. R2 runs on CPU for correctness; R3 sizing pass can introduce GPU if the volume justifies. |
| Cache consistency | `source_sha256` keyed — if source text changes, new cache entry. No invalidation needed. |
| Model version upgrades | `model_name` + `model_version` stored on each cache row. A model upgrade invalidates nothing; new translations use the new model, old ones remain valid until evicted. |

## What did NOT change

* `services/ingest/core/base.py::_assert_runnable` — scope gate still
  in force. Translation is downstream of ingestion and does not relax
  any upstream guardrail.
* Raw payloads stored untranslated per CLAUDE.md §4.1 #2 (raw before
  derived). Translation is derived.
* Original-language text remains the first-class representation in
  canonical storage, search index, and UI (PRD §8.4).

## Links

* CLAUDE.md §5 (stack) — NLLB listed
* PRD §8.4 — multilingual extraction
* `services/translation/` — the service code
* `infra/docker-compose.yaml` — `translation` profile
* `infra/alembic/versions/0002_r2_parser_pipeline.py` — cache table
