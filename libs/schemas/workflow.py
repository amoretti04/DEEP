"""Watchlists and alerting (PRD §13, §14)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AlertChannel(str, Enum):
    EMAIL = "email"
    SLACK = "slack"
    TEAMS = "teams"
    RSS = "rss"
    WEBHOOK = "webhook"


class Watchlist(BaseModel):
    """A saved filter for opportunities or companies.

    Membership can be static (``company_pids``) or dynamic (``filter_dsl``).
    A watchlist with both fields applies them as a union.
    """

    model_config = ConfigDict(extra="forbid")

    watchlist_pid: str = Field(..., min_length=26, max_length=26)
    owner_id: str
    name: str = Field(..., min_length=1, max_length=200)
    company_pids: list[str] = Field(default_factory=list)
    filter_dsl: dict[str, object] | None = Field(
        default=None,
        description=(
            "Versioned JSON DSL for dynamic membership: country, tier, "
            "sector, event_type, score floor. See services/api spec."
        ),
    )
    created_at_utc: datetime
    updated_at_utc: datetime


class AlertRule(BaseModel):
    """User-configured rule that fires on new events."""

    model_config = ConfigDict(extra="forbid")

    rule_pid: str = Field(..., min_length=26, max_length=26)
    owner_id: str
    name: str = Field(..., min_length=1, max_length=200)
    watchlist_pid: str | None = Field(default=None, min_length=26, max_length=26)
    channels: list[AlertChannel] = Field(..., min_length=1)
    min_score: float | None = Field(default=None, ge=0.0, le=100.0)
    only_tier: list[int] = Field(default_factory=list)
    enabled: bool = True
    created_at_utc: datetime


class AlertDelivery(BaseModel):
    """Record of one alert fire — for audit and dedupe."""

    model_config = ConfigDict(extra="forbid")

    delivery_pid: str = Field(..., min_length=26, max_length=26)
    rule_pid: str = Field(..., min_length=26, max_length=26)
    opportunity_pid: str = Field(..., min_length=26, max_length=26)
    channel: AlertChannel
    delivered_at_utc: datetime
    status: str = Field(default="sent", description="sent | failed | suppressed")
    detail: str | None = None
