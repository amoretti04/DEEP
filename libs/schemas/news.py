"""News canonical model."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from libs.schemas.common import Language
from libs.schemas.raw import SourceReference


class Sentiment(str, Enum):
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"
    UNKNOWN = "unknown"


class NewsItem(BaseModel):
    """A news article or press piece about a company or proceeding."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    news_pid: str = Field(..., min_length=26, max_length=26)
    company_pid: str | None = Field(default=None, min_length=26, max_length=26)
    proceeding_pid: str | None = Field(default=None, min_length=26, max_length=26)

    headline: str = Field(..., min_length=1, max_length=500)
    summary: str | None = Field(default=None, max_length=4000)
    url: HttpUrl
    published_at_utc: datetime

    language_original: Language
    sentiment: Sentiment = Sentiment.UNKNOWN

    source_references: list[SourceReference] = Field(..., min_length=1)
