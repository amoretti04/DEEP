"""Provenance primitives for DIP.

Every persisted record carries a :class:`ProvenanceEnvelope`. No record is
written to the canonical store without one; an integration test asserts
this invariant across every model.

Design rules (CLAUDE.md §4.1 #2, §11):

* Raw payloads are immutable in S3 and referenced by content hash.
* ``record_uid`` is deterministic: re-running the pipeline on the same
  payload produces the same id and therefore an idempotent upsert.
* Parser changes bump ``parser_version`` (semver), which is sufficient to
  replay historical raw payloads against a new parser.

This module has no dependencies beyond pydantic and stdlib.
"""

from libs.provenance.envelope import ProvenanceEnvelope, build_envelope
from libs.provenance.identifiers import (
    compute_raw_sha256,
    derive_raw_object_key,
    new_extractor_run_id,
    new_ulid,
    record_uid,
)

__all__ = [
    "ProvenanceEnvelope",
    "build_envelope",
    "compute_raw_sha256",
    "derive_raw_object_key",
    "new_extractor_run_id",
    "new_ulid",
    "record_uid",
]
