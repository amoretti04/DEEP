"""Wire contract shared by the translation client and the translation service."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TranslateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=200_000)
    source_language: str = Field(
        ...,
        pattern=r"^[a-z]{2}(-[A-Z]{2})?$|^auto$",
        description="ISO 639-1 lowercase, optional -REGION, or 'auto'.",
    )
    target_language: str = Field(
        default="en",
        pattern=r"^[a-z]{2}(-[A-Z]{2})?$",
        description="ISO 639-1, defaults to 'en'.",
    )


class TranslateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translated_text: str
    source_language: str = Field(..., description="Detected or echoed source language.")
    target_language: str
    model_name: str
    model_version: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    character_count: int = Field(..., ge=0)
