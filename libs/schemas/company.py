"""Company canonical models.

See CLAUDE.md §12 for the PID scheme. External identifiers are captured
as (scheme, value) pairs so we can add new schemes without migrations.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from libs.schemas.common import Country
from libs.schemas.raw import SourceReference


class IdentifierScheme(str, Enum):
    """Canonical list of identifier schemes (CLAUDE.md §12)."""

    LEI = "lei"                          # ISO 17442 (preferred)
    VAT = "vat"                          # country-prefixed VAT
    CODICE_FISCALE = "codice_fiscale"    # IT
    SIREN = "siren"                      # FR
    SIRET = "siret"                      # FR (establishment)
    HRB = "hrb"                          # DE Handelsregister B-number
    HRA = "hra"                          # DE Handelsregister A-number
    CIF = "cif"                          # ES
    NIF = "nif"                          # ES (natural/legal)
    RSIN = "rsin"                        # NL
    KVK = "kvk"                          # NL Chamber of Commerce
    UID_CH = "uid"                       # CH Unternehmens-ID
    CRN = "crn"                          # UK Companies House number
    ECLI = "ecli"                        # European Case Law Identifier
    INTERNAL = "internal"                # ULID (our own PID)


class CompanyIdentifier(BaseModel):
    """One (scheme, value) pair attached to a :class:`Company`.

    Preferred linkage order: LEI > national registry > VAT > probabilistic.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scheme: IdentifierScheme
    value: str = Field(..., min_length=2, max_length=64)
    verified: bool = False
    verified_at_utc: str | None = None


class CompanyAlias(BaseModel):
    """A name the company has gone by — trading name, prior legal name, etc."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=500)
    alias_type: str = Field(
        default="other",
        description="legal_prior | trading | abbreviation | transliteration | other",
    )
    valid_from: date | None = None
    valid_to: date | None = None


class Company(BaseModel):
    """Canonical company entity."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_pid: str = Field(
        ..., min_length=26, max_length=26, description="Internal ULID PID"
    )
    legal_name: str = Field(..., min_length=1, max_length=500)
    country: Country
    status: str = Field(
        default="active",
        description="active | dissolved | in_proceeding | merged | unknown",
    )
    nace_code: str | None = Field(
        default=None,
        pattern=r"^[A-Z]?\d{1,2}(\.\d{1,2})?$",
        description="EU NACE Rev. 2 code, e.g. '28.11'",
    )
    hq_address: str | None = Field(default=None, max_length=500)
    website: HttpUrl | None = None
    date_founded: date | None = None
    ultimate_parent_pid: str | None = Field(default=None, min_length=26, max_length=26)

    identifiers: list[CompanyIdentifier] = Field(default_factory=list)
    aliases: list[CompanyAlias] = Field(default_factory=list)

    source_references: list[SourceReference] = Field(..., min_length=1)
