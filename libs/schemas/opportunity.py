"""Opportunity, scoring signals, and analyst review.

v1 scoring is rule-based (PRD §12.1). Every surfaced opportunity carries
the signals that contributed to its score so the UI can render the
"why this score?" explanation CLAUDE.md §17 requires.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from libs.schemas.raw import SourceReference


class OpportunityStatus(str, Enum):
    NEW = "new"
    IN_TRIAGE = "in_triage"
    WATCH = "watch"
    DILIGENCE = "diligence"
    PASS = "pass"
    DEAD = "dead"


class AnalystVerdict(str, Enum):
    RELEVANT = "relevant"
    NOT_RELEVANT = "not_relevant"
    UNSURE = "unsure"


class OpportunitySignal(BaseModel):
    """One explainable contributor to an opportunity's score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=80)
    weight: float = Field(..., ge=0.0, le=100.0)
    value: float = Field(..., ge=0.0, le=1.0)
    contribution: float = Field(..., ge=0.0, le=100.0)
    reason: str = Field(..., min_length=1, max_length=500)


class Opportunity(BaseModel):
    """A ranked, scored distressed situation surfaced to the analyst."""

    model_config = ConfigDict(extra="forbid")

    opportunity_pid: str = Field(..., min_length=26, max_length=26)
    company_pid: str = Field(..., min_length=26, max_length=26)
    proceeding_pid: str | None = Field(default=None, min_length=26, max_length=26)

    score: float = Field(..., ge=0.0, le=100.0)
    signals: list[OpportunitySignal] = Field(default_factory=list)
    exclusion_reasons: list[str] = Field(default_factory=list)
    status: OpportunityStatus = OpportunityStatus.NEW

    created_at_utc: datetime
    updated_at_utc: datetime
    scorer_version: str = Field(
        ...,
        pattern=r"^v\d+\.\d+\.\d+$",
        description="Scorer semver, e.g. 'v1.0.0'",
    )

    source_references: list[SourceReference] = Field(..., min_length=1)


class AnalystReview(BaseModel):
    """One analyst's review of an opportunity — feeds ML training in v2."""

    model_config = ConfigDict(extra="forbid")

    review_pid: str = Field(..., min_length=26, max_length=26)
    opportunity_pid: str = Field(..., min_length=26, max_length=26)
    analyst_id: str
    verdict: AnalystVerdict
    notes: str | None = Field(default=None, max_length=4000)
    reviewed_at_utc: datetime
