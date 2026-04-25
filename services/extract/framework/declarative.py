"""Declarative parser — drives off the Source Card ``extraction:`` block.

Covers the ~80% of sources that follow a list→detail pattern. Pure YAML
for new sources; subclass + override for the weird ones.
"""

from __future__ import annotations

import logging
from typing import Any

from services.extract.framework.base import BaseParser, ParsedRecord, ParseError
from services.extract.framework.config import (
    ExtractionConfig,
    FieldConfig,
    FieldProvenance,
)
from services.extract.framework.extractors import ExtractedField, extract_field

logger = logging.getLogger(__name__)


class DeclarativeParser(BaseParser):
    """Parser whose behavior is fully captured by an :class:`ExtractionConfig`.

    Subclass and set :attr:`config` (plus :attr:`PARSER_ID` / :attr:`VERSION`).
    Override :meth:`postprocess` for source-specific cleanups that are
    too domain-specific to express in YAML (e.g. mapping a local
    procedural label to the unified proceeding taxonomy).
    """

    config: ExtractionConfig

    def parse(self, payload: bytes) -> list[ParsedRecord]:
        tree = self._parse_tree(payload)

        # Declarative parser handles one detail page at a time. The
        # pipeline runner invokes the connector to enumerate detail URLs
        # and calls this parser per detail page — so there's exactly one
        # :class:`ParsedRecord` per call in the common case.
        rec = self._parse_record(tree, payload)
        return [rec] if rec is not None else []

    # ── Hook points ────────────────────────────────────────────────
    def postprocess(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Override for source-specific reshaping. Default: identity."""
        return fields

    # ── internals ──────────────────────────────────────────────────
    def _parse_tree(self, payload: bytes) -> Any:
        ct = self.config.content_type
        if ct == "html":
            from selectolax.parser import HTMLParser

            return HTMLParser(payload.decode("utf-8", errors="replace"))
        if ct == "xml":
            return payload.decode("utf-8", errors="replace")  # lxml parses from str in extractors
        if ct == "json":
            import json

            try:
                return json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise ParseError(f"invalid JSON: {e}") from e
        raise ParseError(f"unsupported content_type: {ct}")

    def _apply_root(self, tree: Any) -> Any:
        """Narrow tree to the record root if configured."""
        root = self.config.record.root_selector
        if not root or self.config.content_type != "html":
            return tree
        rooted = tree.css_first(root)
        if rooted is None:
            raise ParseError(f"record.root_selector {root!r} matched nothing")
        return rooted

    def _parse_record(self, tree: Any, payload: bytes) -> ParsedRecord | None:
        rooted = self._apply_root(tree)

        extracted: dict[str, ExtractedField] = {}
        provenance: dict[str, FieldProvenance] = {}
        errors: list[str] = []

        for name, field_cfg in self.config.record.fields.items():
            result = extract_field(name=name, cfg=field_cfg, tree=rooted)
            extracted[name] = result
            if result.error and field_cfg.required:
                errors.append(f"{name}: {result.error}")
            elif result.error:
                errors.append(f"{name} (optional): {result.error}")
            if result.provenance is not None:
                provenance[name] = result.provenance

        if any(
            fc.required and extracted[n].value is None
            for n, fc in self.config.record.fields.items()
        ):
            # Hard extraction failure — record goes to quarantine.
            raise ParseError(
                f"required fields missing: {errors}. "
                f"raw artifact preserved for replay."
            )

        # Compose the typed field dict and let postprocess reshape.
        fields = {name: f.value for name, f in extracted.items() if f.value is not None}
        fields = self.postprocess(fields)

        natural_key = self._derive_natural_key(fields)
        return ParsedRecord(
            natural_key=natural_key,
            fields=fields,
            field_provenance=provenance,
            errors=errors,
            confidence=self._aggregate_confidence(provenance),
        )

    def _derive_natural_key(self, fields: dict[str, Any]) -> str:
        """Combine configured natural-key fields, or fall back to hint."""
        keyfields = self.config.record.natural_key_fields
        if keyfields:
            parts = [str(fields.get(k, "")) for k in keyfields]
            if all(parts):
                return "|".join(parts)
        return self.ctx.natural_key_hint

    @staticmethod
    def _aggregate_confidence(provenance: dict[str, FieldProvenance]) -> float:
        if not provenance:
            return 1.0
        return sum(p.confidence for p in provenance.values()) / len(provenance)
