"""Ingest-side schemas.

A :class:`ConnectorRun` is one invocation of one source. It produces
:class:`RawArtifact`\\ s (immutable blobs in S3) which parsers transform
into :class:`ExtractedRecord`\\ s. Every downstream canonical entity
(Company, Proceeding, Event, Asset, …) carries one or more
:class:`SourceReference`\\ s pointing back to the raw evidence.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from libs.provenance import ProvenanceEnvelope
from libs.schemas.source import SourceId


class ConnectorRunStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"        # some records landed, some failed
    FAILED = "failed"
    CIRCUIT_OPEN = "circuit_open"  # breaker fired before fetching


class ExtractionStatus(str, Enum):
    PARSED = "parsed"
    QUARANTINED = "quarantined"  # validator rejected; human review queue
    DUPLICATE = "duplicate"      # record_uid already seen
    FAILED = "failed"            # parser threw; DLQ


class ConnectorRun(BaseModel):
    """One invocation of one source's connector."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., min_length=26, max_length=26, description="ULID")
    source_id: SourceId
    started_at_utc: datetime
    ended_at_utc: datetime | None = None
    status: ConnectorRunStatus
    artifacts_count: int = Field(0, ge=0)
    records_parsed: int = Field(0, ge=0)
    records_quarantined: int = Field(0, ge=0)
    records_duplicate: int = Field(0, ge=0)
    error_summary: str | None = None
    triggered_by: str = Field(
        "scheduler",
        description="scheduler | manual | webhook | replay",
    )
    source_card_version: int = Field(..., ge=1)


class RawArtifact(BaseModel):
    """An immutable raw payload landed in the lake.

    The ``object_key`` is content-addressed (see
    :func:`libs.provenance.derive_raw_object_key`), so re-fetches of
    identical bytes are no-ops at the storage layer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., min_length=26, max_length=26)
    source_id: SourceId
    object_key: str
    source_url: HttpUrl
    content_type: str = Field(..., description="RFC 6838, e.g. 'text/html'")
    content_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(..., ge=0)
    fetched_at_utc: datetime
    published_at_local: datetime | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)


class SourceReference(BaseModel):
    """Pointer from a canonical entity back to one raw artifact.

    Every Company / Proceeding / Event / Asset / Auction / Filing / NewsItem
    row must carry at least one of these. Without a source reference, the
    data didn't happen — the integration test suite asserts this invariant.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope: ProvenanceEnvelope
    # Denormalized for fast lookups; must match envelope.source_id.
    source_id: SourceId

    def model_post_init(self, _ctx: object) -> None:
        if self.envelope.source_id != self.source_id:
            raise ValueError(
                "SourceReference.source_id must equal envelope.source_id"
            )


class ExtractedRecord(BaseModel):
    """Parser output before normalization.

    One raw artifact can produce multiple extracted records (e.g. a gazette
    page listing 30 insolvency notices).
    """

    model_config = ConfigDict(extra="forbid")

    record_uid: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    run_id: str = Field(..., min_length=26, max_length=26)
    source_id: SourceId
    parser_version: str = Field(
        ..., pattern=r"^[a-z0-9_.]+(\.[a-z0-9_]+)*_v\d+\.\d+\.\d+$"
    )
    raw_object_key: str
    # Flexible payload — the normalizer validates against the target canonical
    # model(s). Keep this loose at the boundary so parsers don't fail hard on
    # schema drift at the normalizer boundary.
    payload: dict[str, object]
    status: ExtractionStatus
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    language: str | None = Field(default=None, max_length=10)
    errors: list[str] = Field(default_factory=list)
