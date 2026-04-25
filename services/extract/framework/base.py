"""BaseParser — what every parser exposes to the pipeline.

A parser maps raw bytes → list of :class:`ExtractedRecord`. The pipeline
is responsible for persistence, envelope assembly, and normalization;
parsers only care about getting the right fields out of the right bytes.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from libs.provenance import ProvenanceEnvelope
from libs.schemas.raw import ExtractedRecord
from services.extract.framework.config import FieldProvenance


class ParseError(Exception):
    """Parser raised; record is routed to the quarantine queue, not dropped."""


@dataclass(slots=True)
class ParseContext:
    """What a parser needs to turn one raw artifact into extracted records.

    Supplied by the pipeline runner. Parsers don't construct this themselves.
    """

    source_id: str
    parser_version: str
    run_id: str
    envelope: ProvenanceEnvelope
    raw_object_key: str
    source_url: str
    # Parsed natural-key hint from the connector (e.g. detail URL's last
    # segment). A parser may override if it finds a better one in the body.
    natural_key_hint: str
    # For list-style sources, list-page fields (published_at, etc.) can
    # flow through here.
    list_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedRecord:
    """Intermediate — typed fields + per-field provenance, pre-serialization.

    The parser produces these; the pipeline converts each to an
    :class:`ExtractedRecord` for persistence.
    """

    natural_key: str
    fields: dict[str, Any]
    field_provenance: dict[str, FieldProvenance]
    language: str | None = None
    confidence: float = 1.0
    errors: list[str] = field(default_factory=list)


class BaseParser(abc.ABC):
    """Inherit this for source-specific parsers that don't fit the declarative mould."""

    #: Parser module path, e.g. ``"parsers.it.tribunale_milano_v1"``.
    PARSER_ID: str
    #: Semver. Bump per CLAUDE.md §10 / `docs/runbooks/onboarding.md`.
    VERSION: str

    def __init__(self, ctx: ParseContext) -> None:
        self.ctx = ctx

    @abc.abstractmethod
    def parse(self, payload: bytes) -> list[ParsedRecord]:
        """Return zero or more :class:`ParsedRecord`\\ s.

        Returning zero records is not an error — a list page with no
        new entries yields an empty list. Raising :class:`ParseError`
        marks the whole artifact as failed (quarantine).
        """
