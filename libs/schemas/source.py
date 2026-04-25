"""Source registry and Source Card schemas.

A :class:`Source` is the registry row — stable identity + current card.
A :class:`SourceCardVersion` captures a committed version of the Source
Card config so historical runs can be audited against the exact rules
that were in effect.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

from libs.schemas.common import (
    Country,
    JurisdictionClass,
    Language,
    LegalReviewStatus,
    Tier,
)
from libs.taxonomy import SourceCategory


class ConnectorType(str, Enum):
    """Connector implementations (PRD §7.2). New ones require an ADR."""

    API = "APIConnector"
    BULK = "BulkConnector"
    HTTP_SCRAPE = "HttpScrapeConnector"
    HEADLESS = "HeadlessConnector"
    MANUAL = "ManualConnector"  # human upload / webhook-triggered


class ParserStatus(str, Enum):
    """Parser lifecycle state (ADR-0006)."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class FetchMode(str, Enum):
    """How a connector walks the source."""

    LIST_AND_DETAIL = "list+detail"
    RSS = "rss"
    API = "api"
    BULK = "bulk"
    WEBHOOK = "webhook"


SourceId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=120,
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description="Kebab-case, country-prefixed. Example: 'it-tribunale-milano-fallimenti'.",
    ),
]


class Politeness(BaseModel):
    """Per-source rate-limit / politeness config (PRD §7.4)."""

    model_config = ConfigDict(extra="forbid")

    min_delay_s: float = Field(4.0, ge=0.0, le=600.0)
    max_delay_s: float = Field(9.0, ge=0.0, le=3600.0)
    concurrency: int = Field(1, ge=1, le=32)
    user_agent_pool: str = "default_eu"
    respect_robots: bool = True
    proxy_pool: str | None = None
    requests_per_minute: int | None = Field(
        default=None,
        ge=1,
        le=6000,
        description="Optional hard cap in addition to delay-based throttling.",
    )

    @field_validator("max_delay_s")
    @classmethod
    def _max_ge_min(cls, v: float, info: object) -> float:
        # pydantic v2: can't access other fields in field_validator trivially;
        # check via a cheap sentinel in data dict on the model validator below.
        return v


class SourceSchedule(BaseModel):
    """When a source should be polled (CLAUDE.md §10)."""

    model_config = ConfigDict(extra="forbid")

    cron: str = Field(..., min_length=9, max_length=100)
    timezone: str = Field("Europe/Rome", max_length=64)
    business_hours_only: bool = False
    off_hours_cron: str | None = Field(
        default=None,
        description=(
            "Optional fallback cron for non-business hours. Typical pattern "
            "for Tier-1: every 3h business hours, every 6h off-hours."
        ),
    )


class LegalReview(BaseModel):
    """LIA metadata embedded in the Source Card (CLAUDE.md §9)."""

    model_config = ConfigDict(extra="forbid")

    verdict: LegalReviewStatus = LegalReviewStatus.PENDING
    date: datetime | None = None
    reviewer: EmailStr | None = None
    lia_path: str | None = Field(
        default=None,
        description="Path to the LIA doc under docs/lia/, e.g. 'docs/lia/it/tribunale-milano.md'",
    )
    notes: str | None = None


class OnFailure(BaseModel):
    """What to do when the connector fails (CLAUDE.md §9, §14)."""

    model_config = ConfigDict(extra="forbid")

    alert_channel: str = Field("slack#ingest-alerts")
    severity_after_minutes: int = Field(30, ge=1, le=1440)
    circuit_breaker_after_consecutive: int = Field(5, ge=1, le=100)
    circuit_breaker_window_minutes: int = Field(30, ge=1, le=1440)


class Source(BaseModel):
    """Canonical source registry row.

    This is the stable identity (``source_id``) plus its *current* card.
    Historical cards are in :class:`SourceCardVersion`. Changing the card
    bumps a version; code always reads the version active at run time.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: SourceId
    name: str = Field(..., min_length=2, max_length=300)

    # From the workbook, preserved verbatim for auditability.
    workbook_country: str = Field(..., min_length=1, max_length=40)
    workbook_category: str | None = None
    workbook_row: int | None = Field(default=None, ge=1)

    # Canonical normalized fields.
    country: Country
    language: Language
    tier: Tier
    category: SourceCategory
    jurisdiction_class: JurisdictionClass

    connector: ConnectorType
    fetch_mode: FetchMode
    base_url: HttpUrl

    schedule: SourceSchedule
    politeness: Politeness = Politeness()
    parser: str | None = Field(
        default=None,
        description="Python module path of the parser, e.g. 'parsers.it.tribunale_milano_v1'.",
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$",
    )
    legal_review: LegalReview = LegalReview()
    owner: str = Field("unassigned", max_length=120)
    on_failure: OnFailure = OnFailure()

    cost_budget_eur_month: int | None = Field(default=None, ge=0, le=100_000)

    # Release-wave tagging (from the blueprint workbook).
    release_wave: int | None = Field(default=None, ge=1, le=8)
    in_priority_scope: bool = Field(
        default=False,
        description=(
            "True for IT/DE/FR/UK/ES/NL/CH + EU. False for UAE/KSA/Global. "
            "UI uses this for the default analyst filter (ADR-0003)."
        ),
    )
    enabled: bool = Field(
        default=False,
        description=(
            "Convenience bit. Scheduler also checks legal_review.verdict; "
            "enabled=True with verdict!=approved must NOT run."
        ),
    )

    status: "ParserStatus" = Field(
        default="unverified",
        description=(
            "Lifecycle state (ADR-0006). "
            "'unverified': selector patterns are scaffolded but not "
            "confirmed against a real captured page. "
            "'verified': selectors have been confirmed via "
            "scripts/verify_selectors.py and a canary fixture exists. "
            "Legacy R1/R2 reference parsers are implicitly verified."
        ),
    )

    # Notes and description from the workbook.
    notes: str | None = None

    @field_validator("politeness")
    @classmethod
    def _delay_ordering(cls, v: Politeness) -> Politeness:
        if v.max_delay_s < v.min_delay_s:
            raise ValueError("politeness.max_delay_s must be >= min_delay_s")
        return v


class SourceCardVersion(BaseModel):
    """Immutable snapshot of a Source Card at a point in time.

    Written whenever a Source Card changes. The active version is the one
    with the highest ``version`` for a given ``source_id``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: SourceId
    version: int = Field(..., ge=1)
    committed_at_utc: datetime
    committed_by: str
    card: Source
    changelog: str | None = None
