"""Declarative parser framework.

The insight that makes 155 parsers tractable: most source pages follow the
same structural pattern — a *list* page with repeating entries, each
linking to a *detail* page with structured fields. A hand-written parser
per source mostly boils down to "which CSS selector picks the debtor
name, which regex pulls the case number, how do we parse the date."

This framework lifts that structure into a declarative :class:`ExtractionConfig`
that lives in the Source Card. A generic :class:`DeclarativeParser`
executes it against raw bytes and emits :class:`ExtractedRecord` objects
with **field-level provenance** — every canonical field carries the
record_uid of the raw artifact it came from plus the selector chain that
extracted it.

Sources that don't fit the declarative mould (weird XML dumps, PDF tables,
JSON APIs with pagination quirks) inherit :class:`BaseParser` and override
:meth:`parse`. Either way, they emit the same :class:`ExtractedRecord`
shape so the normalizer downstream doesn't need to know which path was used.
"""

from services.extract.framework.base import BaseParser, ParseContext, ParseError
from services.extract.framework.config import (
    ExtractionConfig,
    FieldConfig,
    FieldProvenance,
    FieldType,
    ListConfig,
    RecordPath,
)
from services.extract.framework.declarative import DeclarativeParser
from services.extract.framework.declarative_xml import DeclarativeXmlBulkParser
from services.extract.framework.extractors import (
    ExtractedField,
    extract_field,
)

__all__ = [
    "BaseParser",
    "DeclarativeParser",
    "DeclarativeXmlBulkParser",
    "ExtractedField",
    "ExtractionConfig",
    "FieldConfig",
    "FieldProvenance",
    "FieldType",
    "ListConfig",
    "ParseContext",
    "ParseError",
    "RecordPath",
    "extract_field",
]
