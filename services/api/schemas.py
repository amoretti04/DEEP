"""API-facing DTOs.

Distinct from :mod:`libs.schemas`: those are the canonical domain models.
These are the wire-format models — what the API returns to the frontend.
Separation keeps persistence and transport concerns independent.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceSummary(BaseModel):
    """Compact source listing row for /sources."""

    model_config = ConfigDict(from_attributes=True)

    source_id: str
    name: str
    country: str
    language: str
    tier: int
    category: str
    jurisdiction_class: str
    connector: str
    base_url: str
    in_priority_scope: bool
    enabled: bool
    legal_review_verdict: str
    release_wave: int | None
    owner: str

    @classmethod
    def from_orm_row(cls, row: object) -> SourceSummary:
        legal_review = getattr(row, "legal_review", {}) or {}
        return cls(
            source_id=getattr(row, "source_id"),
            name=getattr(row, "name"),
            country=getattr(row, "country"),
            language=getattr(row, "language"),
            tier=getattr(row, "tier"),
            category=getattr(row, "category"),
            jurisdiction_class=getattr(row, "jurisdiction_class"),
            connector=getattr(row, "connector"),
            base_url=getattr(row, "base_url"),
            in_priority_scope=bool(getattr(row, "in_priority_scope")),
            enabled=bool(getattr(row, "enabled")),
            legal_review_verdict=str(legal_review.get("verdict", "unknown")),
            release_wave=getattr(row, "release_wave", None),
            owner=getattr(row, "owner"),
        )


class SourceListResponse(BaseModel):
    items: list[SourceSummary]
    total: int
    limit: int
    offset: int


class CountsByDimension(BaseModel):
    by_country: dict[str, int] = Field(default_factory=dict)
    by_tier: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_jurisdiction_class: dict[str, int] = Field(default_factory=dict)
    total: int = 0
    in_priority_scope: int = 0
    enabled: int = 0


class EventRow(BaseModel):
    event_pid: str
    proceeding_pid: str
    event_type: str
    occurred_at_utc: datetime
    description_original: str
    description_english: str | None = None
    language_original: str | None = None


class EventListResponse(BaseModel):
    items: list[EventRow]
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str
    database: str
    version: str = "0.1.0"


# ── R2 DTOs ──────────────────────────────────────────────────────────
class SourceReferenceRow(BaseModel):
    """Thin wire view of a source_reference row for UI provenance links."""

    model_config = ConfigDict(from_attributes=True)

    record_uid: str
    source_id: str
    source_url: str
    fetched_at_utc: datetime
    parser_version: str
    raw_object_key: str


class DocumentRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_pid: str
    proceeding_pid: str
    title: str
    document_type: str
    url: str | None = None
    raw_object_key: str | None = None
    filed_at: str | None = None
    language_original: str | None = None
    page_count: int | None = None
    has_translation: bool = False


class ProceedingEventWithContext(BaseModel):
    """An event with enough surrounding context for the UI timeline."""

    model_config = ConfigDict(from_attributes=True)

    event_pid: str
    event_type: str
    occurred_at_utc: datetime
    description_original: str
    description_english: str | None = None
    language_original: str | None = None


class ProceedingDetailResponse(BaseModel):
    """What /v1/proceedings/{pid} returns."""

    proceeding_pid: str
    company_pid: str
    jurisdiction: str
    court_name: str | None = None
    court_case_number: str | None = None
    proceeding_type: str
    proceeding_type_original: str
    administrator_name: str | None = None
    administrator_role: str | None = None
    opened_at: str | None = None
    closed_at: str | None = None
    status: str
    events: list[ProceedingEventWithContext] = Field(default_factory=list)
    documents: list[DocumentRow] = Field(default_factory=list)
    source_references: list[SourceReferenceRow] = Field(default_factory=list)


class TranslateDocumentRequest(BaseModel):
    """POST /v1/documents/{pid}/translate body (optional — target defaults to 'en')."""

    model_config = ConfigDict(extra="forbid")

    target_language: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")


class TranslateDocumentResponse(BaseModel):
    """What the translate endpoint returns — text + provenance of the translation."""

    document_pid: str
    source_language: str
    target_language: str
    translated_text: str
    model_name: str
    model_version: str
    from_cache: bool
    character_count: int


class UserSettings(BaseModel):
    """Shape of the settings JSONB column.

    New flags go here (not at the top level) so the DB schema never
    changes when we add a setting. The API enforces this shape; the DB
    stores whatever the API accepted.
    """

    model_config = ConfigDict(extra="forbid")

    class _Translation(BaseModel):
        model_config = ConfigDict(extra="forbid")
        enabled: bool = False
        default_target_language: str = Field(default="en", pattern=r"^[a-z]{2}$")

    class _Display(BaseModel):
        model_config = ConfigDict(extra="forbid")
        show_low_confidence_badge: bool = True
        priority_scope_only_by_default: bool = True

    translation: _Translation = Field(default_factory=lambda: UserSettings._Translation())
    display: _Display = Field(default_factory=lambda: UserSettings._Display())


class UserSettingsResponse(BaseModel):
    user_id: str
    settings: UserSettings
    updated_at: datetime
