"""Provenance envelope attached to every persisted record.

See CLAUDE.md §11 and PRD §8.2. The envelope is immutable once written;
upserts target the canonical record, not the envelope.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from libs.provenance.identifiers import record_uid


class ProvenanceEnvelope(BaseModel):
    """Immutable provenance for a single canonical record.

    A downstream consumer that has the envelope can always find the raw
    bytes (via ``raw_object_key`` + ``raw_sha256``), the source page (via
    ``source_url``), the parser version that produced the record, and the
    legal basis under which we processed it.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    record_uid: str = Field(
        ...,
        pattern=r"^sha256:[0-9a-f]{64}$",
        description="Deterministic, content-addressed record id.",
    )
    source_id: str = Field(..., min_length=1, max_length=200)
    source_url: str = Field(..., min_length=1)
    fetched_at_utc: datetime
    published_at_local: datetime | None = Field(
        default=None,
        description=(
            "Publication time in the source's local tz. None if the source "
            "does not emit a timestamp."
        ),
    )
    raw_object_key: str = Field(
        ..., description="S3 key; format: <source_id>/<YYYY>/<MM>/<DD>/<sha256>.<ext>"
    )
    raw_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    parser_version: str = Field(
        ...,
        pattern=r"^[a-z0-9_.]+(\.[a-z0-9_]+)*_v\d+\.\d+\.\d+$",
        description="Module path + semver, e.g. 'it.tribunale_milano_v1.2.1'",
    )
    extractor_run_id: str = Field(..., min_length=26, max_length=26)
    data_owner: str = Field(..., min_length=1)
    legal_basis: str = Field(
        ...,
        min_length=1,
        description="Free-text legal basis; typically references Art. 6(1)(f) GDPR.",
    )

    # ── Invariants ─────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _timestamps_are_utc(self) -> Self:
        if self.fetched_at_utc.tzinfo is None:
            raise ValueError("fetched_at_utc must be timezone-aware")
        if self.fetched_at_utc > datetime.now(UTC):
            raise ValueError("fetched_at_utc cannot be in the future")
        if (
            self.published_at_local is not None
            and self.published_at_local.tzinfo is None
        ):
            raise ValueError("published_at_local must be timezone-aware if set")
        return self


def build_envelope(
    *,
    source_id: str,
    source_url: str,
    stable_natural_key: str,
    fetched_at_utc: datetime,
    published_at_local: datetime | None,
    raw_object_key: str,
    raw_sha256: str,
    parser_version: str,
    extractor_run_id: str,
    data_owner: str,
    legal_basis: str,
) -> ProvenanceEnvelope:
    """Convenience constructor that computes ``record_uid`` for the caller.

    Most call sites have the stable natural key handy but not the hash, so
    we accept the key and do the derivation here.
    """
    published_utc = (
        published_at_local.astimezone(UTC) if published_at_local else None
    )
    rid = record_uid(
        source_id=source_id,
        stable_natural_key=stable_natural_key,
        published_at_utc=published_utc,
    )
    return ProvenanceEnvelope(
        record_uid=rid,
        source_id=source_id,
        source_url=source_url,
        fetched_at_utc=fetched_at_utc,
        published_at_local=published_at_local,
        raw_object_key=raw_object_key,
        raw_sha256=raw_sha256,
        parser_version=parser_version,
        extractor_run_id=extractor_run_id,
        data_owner=data_owner,
        legal_basis=legal_basis,
    )
