"""Canonical domain schemas for DIP.

Pydantic v2 models, independent of any persistence layer. ORM models live
next to the Alembic migrations in ``infra/alembic`` and are derived from
these; these are the boundary contracts (connector → parser → normalizer
→ scorer → API).

Design rules:

* Every model that represents a persisted entity carries at least one
  :class:`~libs.schemas.raw.SourceReference`. No orphan data. This is
  enforced by tests at the model boundary.
* Enums live in :mod:`libs.schemas.common`; never inline enum strings.
* All monetary amounts carry an ISO-4217 currency code; never bare floats.
* All datetimes are timezone-aware UTC unless the field explicitly names
  ``_local`` (e.g. ``published_at_local``).
"""

from libs.schemas.admin import AuditLog, User, UserRole
from libs.schemas.asset import Asset, AssetClass, Auction, AuctionMethod, AuctionOutcome
from libs.schemas.common import (
    Country,
    JurisdictionClass,
    Language,
    LegalReviewStatus,
    Money,
    Tier,
)
from libs.schemas.company import Company, CompanyAlias, CompanyIdentifier, IdentifierScheme
from libs.schemas.filing import Filing, FilingType
from libs.schemas.news import NewsItem, Sentiment
from libs.schemas.opportunity import (
    AnalystReview,
    AnalystVerdict,
    Opportunity,
    OpportunitySignal,
    OpportunityStatus,
)
from libs.schemas.proceeding import (
    Proceeding,
    ProceedingDocument,
    ProceedingEvent,
    ProceedingEventType,
    ProceedingStatus,
)
from libs.schemas.raw import (
    ConnectorRun,
    ConnectorRunStatus,
    ExtractedRecord,
    ExtractionStatus,
    RawArtifact,
    SourceReference,
)
from libs.schemas.source import (
    ConnectorType,
    FetchMode,
    Politeness,
    Source,
    SourceCardVersion,
    SourceSchedule,
)
from libs.schemas.workflow import AlertChannel, AlertDelivery, AlertRule, Watchlist

__all__ = [
    # admin
    "AuditLog",
    "User",
    "UserRole",
    # asset
    "Asset",
    "AssetClass",
    "Auction",
    "AuctionMethod",
    "AuctionOutcome",
    # common
    "Country",
    "JurisdictionClass",
    "Language",
    "LegalReviewStatus",
    "Money",
    "Tier",
    # company
    "Company",
    "CompanyAlias",
    "CompanyIdentifier",
    "IdentifierScheme",
    # filing
    "Filing",
    "FilingType",
    # news
    "NewsItem",
    "Sentiment",
    # opportunity
    "AnalystReview",
    "AnalystVerdict",
    "Opportunity",
    "OpportunitySignal",
    "OpportunityStatus",
    # proceeding
    "Proceeding",
    "ProceedingDocument",
    "ProceedingEvent",
    "ProceedingEventType",
    "ProceedingStatus",
    # raw / ingest
    "ConnectorRun",
    "ConnectorRunStatus",
    "ExtractedRecord",
    "ExtractionStatus",
    "RawArtifact",
    "SourceReference",
    # source
    "ConnectorType",
    "FetchMode",
    "Politeness",
    "Source",
    "SourceCardVersion",
    "SourceSchedule",
    # workflow
    "AlertChannel",
    "AlertDelivery",
    "AlertRule",
    "Watchlist",
]
