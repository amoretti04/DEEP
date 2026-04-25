"""Normalizer — turn ParsedRecords into canonical DB rows.

A parser emits ``ParsedRecord`` objects (domain-typed fields + per-field
provenance) in memory. The normalizer is the missing link that writes
them to Postgres as Company / Proceeding / ProceedingEvent / Document /
ParsedField / SourceReference rows, with idempotency driven by
``record_uid`` and the canonical natural keys.

Idempotency contract:

* Same ``record_uid`` processed twice → no duplicate rows. Re-running
  the pipeline is safe.
* Two distinct source records about the same proceeding (gazette notice
  + tribunal page, for example) → two ``ExtractedRecord``s, but the
  normalizer recognizes the shared ``(jurisdiction, court_case_number)``
  and links them to the same ``Proceeding`` with two ``SourceReference``
  rows. (R3 cross-source resolution is minimal — jurisdiction + case
  number only. R4 introduces LEI / national-ID matching per PRD §9.)

Out of scope for R3:

* Probabilistic entity resolution (Fellegi-Sunter) — R4.
* Analyst-facing merge/unmerge tool — R5.
* Translation enqueue — R2 translation endpoint is strictly on-demand.
"""

from services.normalize.pipeline import NormalizedOutput, Normalizer

__all__ = ["NormalizedOutput", "Normalizer"]
