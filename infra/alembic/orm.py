"""SQLAlchemy 2.0 async ORM models.

Each model mirrors its pydantic counterpart in :mod:`libs.schemas`.
Pydantic is the boundary contract; SQLAlchemy is the storage contract.
We keep them separate rather than trying to share one class so that DB
concerns (index choice, cascade, ONUPDATE, server defaults) don't
contaminate the validation models.

Release 1 ships the minimum tables the blueprint importer and the
scheduler need. Additional tables (opportunity, analyst_review,
watchlist, alert_rule, audit_log) come in R4+ when their code paths
need persistence.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared metadata. PG-native JSONB used where portability isn't needed."""

    type_annotation_map = {dict[str, Any]: JSONB}


def _now() -> datetime:
    # Server-default preferred; this is for in-Python defaults like tests.
    from datetime import UTC

    return datetime.now(UTC)


# ─────────────────────────────────────────────────────────────────────
# Source registry
# ─────────────────────────────────────────────────────────────────────
class SourceOrm(Base):
    __tablename__ = "source"

    source_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)

    # Workbook provenance
    workbook_country: Mapped[str] = mapped_column(String(40), nullable=False)
    workbook_category: Mapped[str | None] = mapped_column(String(300))
    workbook_row: Mapped[int | None] = mapped_column(Integer)

    # Canonical normalized
    country: Mapped[str] = mapped_column(String(4), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    jurisdiction_class: Mapped[str] = mapped_column(String(40), nullable=False)

    connector: Mapped[str] = mapped_column(String(40), nullable=False)
    fetch_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)

    schedule: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    politeness: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    parser: Mapped[str | None] = mapped_column(String(300))

    legal_review: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default="unassigned")
    on_failure: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    cost_budget_eur_month: Mapped[int | None] = mapped_column(Integer)
    release_wave: Mapped[int | None] = mapped_column(Integer)
    in_priority_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    notes: Mapped[str | None] = mapped_column(Text)

    # Top-level keyword pack + collection profiles (from the implementation blueprint)
    keyword_pack: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    company_info_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    document_collection_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    versions: Mapped[list[SourceCardVersionOrm]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    runs: Mapped[list[ConnectorRunOrm]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("tier IN (1, 2, 3)", name="ck_source_tier"),
        Index("ix_source_country_tier", "country", "tier"),
        Index("ix_source_priority_enabled", "in_priority_scope", "enabled"),
        Index("ix_source_category", "category"),
    )


class SourceCardVersionOrm(Base):
    __tablename__ = "source_card_version"

    source_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("source.source_id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    committed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    card: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text)

    source: Mapped[SourceOrm] = relationship(back_populates="versions")


# ─────────────────────────────────────────────────────────────────────
# Ingest
# ─────────────────────────────────────────────────────────────────────
class ConnectorRunOrm(Base):
    __tablename__ = "connector_run"

    run_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("source.source_id", ondelete="CASCADE"), nullable=False
    )
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    artifacts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_parsed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_quarantined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(String(30), nullable=False, default="scheduler")
    source_card_version: Mapped[int] = mapped_column(Integer, nullable=False)

    source: Mapped[SourceOrm] = relationship(back_populates="runs")

    __table_args__ = (
        Index("ix_run_source_started", "source_id", "started_at_utc"),
        Index("ix_run_status", "status"),
    )


class RawArtifactOrm(Base):
    __tablename__ = "raw_artifact"

    object_key: Mapped[str] = mapped_column(String(500), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("connector_run.run_id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("source.source_id", ondelete="CASCADE"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_type: Mapped[str] = mapped_column(String(200), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at_local: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_raw_source_fetched", "source_id", "fetched_at_utc"),
        UniqueConstraint("content_sha256", name="uq_raw_sha"),
    )


class ExtractedRecordOrm(Base):
    __tablename__ = "extracted_record"

    record_uid: Mapped[str] = mapped_column(String(80), primary_key=True)  # 'sha256:' + 64 hex
    run_id: Mapped[str] = mapped_column(String(26), nullable=False)
    source_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("source.source_id", ondelete="CASCADE"), nullable=False
    )
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    raw_object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    language: Mapped[str | None] = mapped_column(String(10))
    errors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        Index("ix_extracted_source_status", "source_id", "status"),
    )


# ─────────────────────────────────────────────────────────────────────
# Canonical domain
# ─────────────────────────────────────────────────────────────────────
class CompanyOrm(Base):
    __tablename__ = "company"

    company_pid: Mapped[str] = mapped_column(String(26), primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(500), nullable=False)
    country: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    nace_code: Mapped[str | None] = mapped_column(String(12))
    hq_address: Mapped[str | None] = mapped_column(String(500))
    website: Mapped[str | None] = mapped_column(String(2048))
    date_founded: Mapped[date | None] = mapped_column(Date)
    ultimate_parent_pid: Mapped[str | None] = mapped_column(String(26))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_company_country_status", "country", "status"),
        Index("ix_company_legal_name_trgm", "legal_name"),
    )


class CompanyIdentifierOrm(Base):
    __tablename__ = "company_identifier"

    company_pid: Mapped[str] = mapped_column(
        String(26), ForeignKey("company.company_pid", ondelete="CASCADE"), primary_key=True
    )
    scheme: Mapped[str] = mapped_column(String(30), primary_key=True)
    value: Mapped[str] = mapped_column(String(64), primary_key=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("scheme", "value", name="uq_identifier_scheme_value"),
    )


class ProceedingOrm(Base):
    __tablename__ = "proceeding"

    proceeding_pid: Mapped[str] = mapped_column(String(26), primary_key=True)
    company_pid: Mapped[str] = mapped_column(
        String(26), ForeignKey("company.company_pid", ondelete="CASCADE"), nullable=False
    )
    jurisdiction: Mapped[str] = mapped_column(String(4), nullable=False)
    court_name: Mapped[str | None] = mapped_column(String(300))
    court_case_number: Mapped[str | None] = mapped_column(String(120))
    proceeding_type: Mapped[str] = mapped_column(String(40), nullable=False)
    proceeding_type_original: Mapped[str] = mapped_column(String(300), nullable=False)
    administrator_name: Mapped[str | None] = mapped_column(String(300))
    administrator_role: Mapped[str | None] = mapped_column(String(100))
    opened_at: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")

    __table_args__ = (
        Index("ix_proc_company", "company_pid"),
        Index("ix_proc_status_opened", "status", "opened_at"),
    )


class ProceedingEventOrm(Base):
    __tablename__ = "proceeding_event"

    event_pid: Mapped[str] = mapped_column(String(26), primary_key=True)
    proceeding_pid: Mapped[str] = mapped_column(
        String(26), ForeignKey("proceeding.proceeding_pid", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    description_original: Mapped[str] = mapped_column(Text, nullable=False)
    description_english: Mapped[str | None] = mapped_column(Text)
    language_original: Mapped[str | None] = mapped_column(String(10))
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_event_proc_occurred", "proceeding_pid", "occurred_at_utc"),
        Index("ix_event_type_occurred", "event_type", "occurred_at_utc"),
    )


class SourceReferenceOrm(Base):
    """Join table — every canonical entity is referenced back to raw evidence.

    Stored polymorphically: (entity_type, entity_id) points at any
    canonical row. Enforcing ≥1 reference is a service-layer invariant
    checked at write time, not a DB-level constraint (cross-table `EXISTS`
    checks are expensive).
    """

    __tablename__ = "source_reference"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    record_uid: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_srcref_entity", "entity_type", "entity_id"),
        Index("ix_srcref_source", "source_id"),
        UniqueConstraint(
            "entity_type", "entity_id", "record_uid",
            name="uq_srcref_entity_record",
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# Import-time review queue (for blueprint UNKNOWN category rows, ADR-0003)
# ─────────────────────────────────────────────────────────────────────
class SourceReviewQueueOrm(Base):
    __tablename__ = "source_review_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_review_unresolved", "resolved_at", "reason"),
    )

# ─────────────────────────────────────────────────────────────────────
# R2 — Parser pipeline: field-level provenance, documents, translations
# ─────────────────────────────────────────────────────────────────────
class ParsedFieldOrm(Base):
    """Field-level provenance — one row per extracted field.

    Enables the UI to answer "show me the exact selector + byte offset
    that produced this value" and gives the analyst-correction tool a
    precise anchor to override a single field without touching the rest
    of the record.
    """

    __tablename__ = "parsed_field"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_uid: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("extracted_record.record_uid", ondelete="CASCADE"),
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    # Value is JSONB so we preserve types (date, decimal, string, list).
    value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_text: Mapped[str | None] = mapped_column(Text)
    selector: Mapped[str] = mapped_column(String(500), nullable=False)
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    raw_length: Mapped[int | None] = mapped_column(Integer)
    transforms: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    pii_tag: Mapped[str] = mapped_column(
        String(30), nullable=False, default="non_personal"
    )
    # Set when an analyst manually overrides the extracted value. The
    # original remains immutable in `value`; the override is recorded
    # here for audit.
    override_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overridden_by: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        Index("ix_parsed_field_record", "record_uid"),
        Index("ix_parsed_field_name", "record_uid", "field_name"),
        UniqueConstraint("record_uid", "field_name", name="uq_parsed_field"),
    )


class DocumentOrm(Base):
    """Document attached to a proceeding (court order, plan, PDF).

    Distinct from raw_artifact: raw_artifact is what the connector
    fetched from the list/detail pages; Document is a *linked* file the
    detail page references (sentenze, decreti, etc.). Translations are
    keyed off this table, not off raw_artifact.
    """

    __tablename__ = "proceeding_document"

    document_pid: Mapped[str] = mapped_column(String(26), primary_key=True)
    proceeding_pid: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("proceeding.proceeding_pid", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="other"
    )
    url: Mapped[str | None] = mapped_column(String(2048))
    raw_object_key: Mapped[str | None] = mapped_column(String(500))
    filed_at: Mapped[date | None] = mapped_column(Date)
    language_original: Mapped[str | None] = mapped_column(String(10))
    text_original: Mapped[str | None] = mapped_column(Text)
    text_english: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_document_proceeding", "proceeding_pid"),
    )


class TranslationOrm(Base):
    """On-demand translation cache.

    Keyed by (content_sha256, target_language). First request hits NLLB;
    subsequent requests return from this cache. The sha256 lets us share
    a single cached translation across multiple records that happen to
    share identical source text.

    Eviction policy (R3+): LRU with a 90-day ceiling, refreshed whenever
    a record referencing the translation is served.
    """

    __tablename__ = "translation_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_language: Mapped[str] = mapped_column(String(10), nullable=False)
    target_language: Mapped[str] = mapped_column(String(10), nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "source_sha256", "target_language",
            name="uq_translation_source_target",
        ),
        Index("ix_translation_last_used", "last_used_at"),
    )


class UserSettingsOrm(Base):
    """Per-user settings (feature flags, display preferences).

    Stored as JSONB so we can add new flags without migrations. The
    shape is validated at the API boundary by a Pydantic model; the DB
    stores whatever the API accepted.
    """

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
