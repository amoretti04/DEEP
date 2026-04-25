"""Enums and value types shared across canonical models.

Keep this module free of dependencies on any other schemas module — it is
imported from all of them.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Tier(int, Enum):
    """Source tier (CLAUDE.md §5.2)."""

    T1 = 1
    T2 = 2
    T3 = 3


class Country(str, Enum):
    """ISO 3166-1 alpha-2 country codes for jurisdictions we currently touch.

    Distinct from ``workbook_country`` free text (e.g. "KSA/MENA",
    "Global") — those are preserved on :class:`Source.workbook_country`.
    """

    IT = "IT"
    DE = "DE"
    FR = "FR"
    UK = "UK"   # ISO would prefer "GB"; we keep UK to match PRD + UX
    ES = "ES"
    NL = "NL"
    CH = "CH"
    # Non-EU scope per ADR-0003
    AE = "AE"   # UAE
    SA = "SA"   # KSA
    # Buckets for non-national sources
    EU = "EU"
    GLOBAL = "XX"


class JurisdictionClass(str, Enum):
    """Legal-regime bucketing used for LIA routing (ADR-0003)."""

    EU_GDPR = "eu_gdpr"
    EEA_GDPR_ADEQUACY = "eea_gdpr_adequacy"
    NON_EU_SEPARATE_REGIME = "non_eu_separate_regime"
    GLOBAL_CASE_BY_CASE = "global_case_by_case"


class Language(str, Enum):
    """ISO 639-1 codes covering the languages we actively extract."""

    IT = "it"
    DE = "de"
    FR = "fr"
    ES = "es"
    NL = "nl"
    EN = "en"
    AR = "ar"
    MULTI = "multi"


class LegalReviewStatus(str, Enum):
    """State of the per-source LIA (CLAUDE.md §3.2, §9).

    ``pending`` — imported but not yet reviewed; scheduler MUST skip.
    ``in_review`` — counsel is assessing; scheduler MUST skip.
    ``approved`` — LIA on file; connector may run in production.
    ``rejected`` — do not fetch; documented in the Source Card.
    """

    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


# ── Money ────────────────────────────────────────────────────────────
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$", description="ISO 4217")]
# Use Decimal so arithmetic on monetary amounts is exact by default.
Amount = Annotated[Decimal, Field(ge=Decimal("0"), max_digits=18, decimal_places=2)]


class Money(BaseModel):
    """Monetary amount with explicit currency.

    Float is never acceptable for money. Decimal with fixed scale, always
    paired with an ISO-4217 currency — enforced by validator.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: Amount
    currency: Currency

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()
