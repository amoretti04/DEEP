"""Filings (registry, disclosure, gazette)."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from libs.schemas.raw import SourceReference


class FilingType(str, Enum):
    ACCOUNTS = "accounts"
    SHAREHOLDER_CHANGE = "shareholder_change"
    DIRECTOR_CHANGE = "director_change"
    STATUS_CHANGE = "status_change"
    CHARGE = "charge"
    DISSOLUTION = "dissolution"
    REGISTRATION = "registration"
    DISCLOSURE = "disclosure"
    OTHER = "other"


class Filing(BaseModel):
    """A formal filing made by or about a company.

    Distinct from :class:`~libs.schemas.proceeding.ProceedingDocument`:
    filings are registry / regulator artifacts about the company itself,
    documents are court-case artifacts.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    filing_pid: str = Field(..., min_length=26, max_length=26)
    company_pid: str = Field(..., min_length=26, max_length=26)
    registry: str = Field(..., min_length=1, max_length=200)
    filing_type: FilingType
    filed_at: date | None = None
    url: HttpUrl | None = None
    raw_object_key: str | None = None
    summary: str | None = Field(default=None, max_length=4000)

    source_references: list[SourceReference] = Field(..., min_length=1)
