"""Asset and Auction canonical models.

The ``AssetClass`` taxonomy exists specifically to enforce PRD §3.2 /
CLAUDE.md §3.3: residential-only real estate and consumer items are out
of scope. :class:`Asset.asset_class` combined with ``tied_to_operating_
business`` makes scope-filtering a database predicate, not a heuristic.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from libs.schemas.common import Money
from libs.schemas.raw import SourceReference


class AssetClass(str, Enum):
    """Canonical asset classification (PRD §11.3)."""

    GOING_CONCERN_BUSINESS = "going_concern_business"
    PLANT_AND_EQUIPMENT = "plant_and_equipment"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    REAL_ESTATE_BUSINESS_USE = "real_estate_business_use"
    INVENTORY = "inventory"
    RECEIVABLES = "receivables"
    # Out-of-scope buckets preserved for completeness; UI filters them.
    RESIDENTIAL_REAL_ESTATE = "residential_real_estate"
    CONSUMER_GOODS = "consumer_goods"
    OTHER = "other"


class AuctionMethod(str, Enum):
    ENGLISH = "english"
    DUTCH = "dutch"
    SEALED_BID = "sealed_bid"
    NEGOTIATED = "negotiated"
    HYBRID = "hybrid"
    OTHER = "other"


class AuctionOutcome(str, Enum):
    PENDING = "pending"
    SOLD = "sold"
    UNSOLD = "unsold"
    CANCELLED = "cancelled"
    WITHDRAWN = "withdrawn"


class Asset(BaseModel):
    """A saleable unit within a proceeding.

    ``tied_to_operating_business`` is the key scope gate: industrial real
    estate tied to an operating business is IN scope even though the
    asset_class is real-estate-flavored; standalone residential buildings
    are OUT.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    asset_pid: str = Field(..., min_length=26, max_length=26)
    proceeding_pid: str = Field(..., min_length=26, max_length=26)
    asset_class: AssetClass
    tied_to_operating_business: bool = Field(
        default=False,
        description=(
            "Scope gate: industrial RE tied to an operating business is IN; "
            "standalone residential is OUT. CLAUDE.md §3.3."
        ),
    )
    description_original: str = Field(..., min_length=1, max_length=5000)
    description_english: str | None = Field(default=None, max_length=5000)
    reserve_price: Money | None = None
    estimated_value: Money | None = None
    auction_pid: str | None = Field(default=None, min_length=26, max_length=26)

    source_references: list[SourceReference] = Field(..., min_length=1)


class Auction(BaseModel):
    """An auction event for one or more :class:`Asset`\\ s."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    auction_pid: str = Field(..., min_length=26, max_length=26)
    asset_pids: list[str] = Field(..., min_length=1)
    platform: str = Field(..., min_length=1, max_length=200)
    platform_url: HttpUrl | None = None
    method: AuctionMethod = AuctionMethod.OTHER
    opens_at_utc: datetime | None = None
    closes_at_utc: datetime | None = None
    outcome: AuctionOutcome = AuctionOutcome.PENDING
    clearing_price: Money | None = None

    source_references: list[SourceReference] = Field(..., min_length=1)
