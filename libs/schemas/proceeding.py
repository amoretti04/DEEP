"""Proceeding, event, and document schemas.

A :class:`Proceeding` is one bankruptcy / insolvency / reorganization
procedure. It has a stream of :class:`ProceedingEvent` rows (filings,
rulings, meetings) and a bag of :class:`ProceedingDocument`\\ s (PDFs,
court orders, plans).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from libs.schemas.common import Country, Language
from libs.schemas.raw import SourceReference
from libs.taxonomy import UnifiedProceedingType


class ProceedingStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    CONVERTED = "converted"   # e.g. reorganization → liquidation
    DISMISSED = "dismissed"
    UNKNOWN = "unknown"


class ProceedingEventType(str, Enum):
    """Unified event taxonomy across jurisdictions (PRD §8.4)."""

    BANKRUPTCY_FILING = "bankruptcy_filing"
    INSOLVENCY_DECLARATION = "insolvency_declaration"
    REORGANIZATION_FILING = "reorganization_filing"
    ADMINISTRATION_APPOINTMENT = "administration_appointment"
    TRUSTEE_APPOINTMENT = "trustee_appointment"
    MORATORIUM_GRANTED = "moratorium_granted"
    CREDITOR_MEETING = "creditor_meeting"
    PLAN_SUBMITTED = "plan_submitted"
    PLAN_APPROVED = "plan_approved"
    PLAN_REJECTED = "plan_rejected"
    ASSET_AUCTION = "asset_auction"
    GOING_CONCERN_SALE = "going_concern_sale"
    DIP_FINANCING = "dip_financing"
    PROCEEDING_CLOSED = "proceeding_closed"
    OTHER = "other"


class ProceedingDocument(BaseModel):
    """A document attached to a proceeding — court order, plan, notice, PDF."""

    model_config = ConfigDict(extra="forbid")

    document_pid: str = Field(..., min_length=26, max_length=26)
    proceeding_pid: str = Field(..., min_length=26, max_length=26)
    title: str = Field(..., min_length=1, max_length=500)
    document_type: str = Field(
        default="other",
        description="filing | ruling | plan | notice | report | other",
    )
    filed_at: date | None = None
    url: HttpUrl | None = None
    raw_object_key: str | None = None
    language_original: Language | None = None
    text_original: str | None = None
    text_english: str | None = None
    page_count: int | None = Field(default=None, ge=0)
    source_references: list[SourceReference] = Field(..., min_length=1)


class ProceedingEvent(BaseModel):
    """A dated event in a proceeding's lifecycle."""

    model_config = ConfigDict(extra="forbid")

    event_pid: str = Field(..., min_length=26, max_length=26)
    proceeding_pid: str = Field(..., min_length=26, max_length=26)
    event_type: ProceedingEventType
    occurred_at_utc: datetime
    description_original: str = Field(..., min_length=1, max_length=5000)
    description_english: str | None = Field(default=None, max_length=5000)
    language_original: Language | None = None
    extra: dict[str, object] = Field(default_factory=dict)
    source_references: list[SourceReference] = Field(..., min_length=1)


class Proceeding(BaseModel):
    """One insolvency / restructuring proceeding."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    proceeding_pid: str = Field(..., min_length=26, max_length=26)
    company_pid: str = Field(..., min_length=26, max_length=26)

    jurisdiction: Country
    court_name: str | None = Field(default=None, max_length=300)
    court_case_number: str | None = Field(default=None, max_length=120)

    # Keep both: unified for cross-jurisdiction analytics, original for audit.
    proceeding_type: UnifiedProceedingType
    proceeding_type_original: str = Field(..., min_length=1, max_length=300)

    administrator_name: str | None = Field(default=None, max_length=300)
    administrator_role: str | None = Field(default=None, max_length=100)

    opened_at: date | None = None
    closed_at: date | None = None
    status: ProceedingStatus = ProceedingStatus.OPEN

    source_references: list[SourceReference] = Field(..., min_length=1)
