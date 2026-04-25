"""Declarative XML-bulk parser — one payload yields many records.

Covers sources like BODACC (FR daily XML dump), BOE Sección II-C (ES XML),
Insolvenzbekanntmachungen bulk RSS. The list concept and the record
concept collapse into one: each matching XML node *is* a record.

Config requires a ``records_xpath`` that selects the container element.
For every matched element, the regular ``record.fields`` are extracted
relative to that element.
"""

from __future__ import annotations

import logging
from typing import Any

from lxml import etree

from services.extract.framework.base import BaseParser, ParsedRecord, ParseError
from services.extract.framework.config import (
    ExtractionConfig,
    FieldConfig,
    FieldProvenance,
    FieldType,
)
from services.extract.framework.extractors import _convert  # reuse type conversion

logger = logging.getLogger(__name__)


class DeclarativeXmlBulkParser(BaseParser):
    """Declarative parser for XML sources where one file holds N records.

    Unlike :class:`DeclarativeParser`, this one:
      * always uses the xpath route,
      * iterates the ``records_xpath`` matches,
      * extracts each via relative xpath,
      * produces a list of :class:`ParsedRecord` — not just one.
    """

    #: Absolute xpath to the repeating record element (e.g. ``//annonce``).
    records_xpath: str
    config: ExtractionConfig

    def parse(self, payload: bytes) -> list[ParsedRecord]:
        try:
            tree = etree.fromstring(payload)
        except etree.XMLSyntaxError as e:
            raise ParseError(f"invalid XML: {e}") from e

        nodes = tree.xpath(self.records_xpath)
        if not isinstance(nodes, list):
            raise ParseError(
                f"records_xpath {self.records_xpath!r} must return a node-set, "
                f"got {type(nodes).__name__}"
            )

        out: list[ParsedRecord] = []
        for node in nodes:
            if not isinstance(node, etree._Element):
                continue
            try:
                rec = self._extract_one(node)
            except ParseError as e:
                logger.warning("bulk.record_skipped %s", e)
                continue  # drop bad records, keep going — bulk files often have partial dirt
            if rec is not None:
                out.append(rec)
        return out

    # ── hooks ──────────────────────────────────────────────────────
    def postprocess(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Override for per-record domain reshaping."""
        return fields

    # ── internals ──────────────────────────────────────────────────
    def _extract_one(self, root: etree._Element) -> ParsedRecord | None:
        provenance: dict[str, FieldProvenance] = {}
        extracted: dict[str, Any] = {}
        errors: list[str] = []

        for name, fc in self.config.record.fields.items():
            value, raw_text, err = self._extract_field(root, fc)
            if err:
                errors.append(f"{name}: {err}")
                if fc.required:
                    raise ParseError(
                        f"required field {name!r} missing: {err}"
                    )
                continue
            extracted[name] = value
            provenance[name] = FieldProvenance(
                field_name=name,
                selector=f"xpath={fc.xpath}" if fc.xpath else f"selector={fc.selector}",
                raw_length=len(raw_text) if raw_text else None,
                transforms=list(fc.transforms),
                confidence=1.0,
            )

        fields = self.postprocess(extracted)
        natural_key = self._derive_natural_key(fields)
        return ParsedRecord(
            natural_key=natural_key,
            fields=fields,
            field_provenance=provenance,
            errors=errors,
        )

    def _extract_field(
        self, root: etree._Element, fc: FieldConfig
    ) -> tuple[Any, str | None, str | None]:
        """Return ``(value, raw_text, error)``. xpath-only path."""
        if not fc.xpath:
            return (None, None, "xml bulk parser requires xpath selector")

        hits = root.xpath(fc.xpath)
        if not hits:
            if fc.default is not None:
                return (fc.default, None, None)
            if fc.required:
                return (None, None, f"xpath {fc.xpath!r} not found")
            return (None, None, None)

        hit = hits[0]
        if isinstance(hit, etree._Element):
            raw = (hit.text or "").strip()
        else:
            raw = str(hit).strip()

        if not raw:
            if fc.required:
                return (None, None, f"xpath {fc.xpath!r} matched empty")
            return (fc.default, None, None)

        # Regex post-process
        if fc.regex:
            import re as _re

            m = _re.search(fc.regex, raw, _re.DOTALL)
            if not m:
                if fc.required:
                    return (None, raw, f"regex {fc.regex!r} did not match")
                return (fc.default, raw, None)
            raw = m.group(1) if m.groups() else m.group(0)

        if fc.strip:
            raw = raw.strip()

        value, err = _convert(raw, fc)
        return (value, raw, err)

    def _derive_natural_key(self, fields: dict[str, Any]) -> str:
        keyfields = self.config.record.natural_key_fields
        if keyfields:
            parts = [str(fields.get(k, "")) for k in keyfields]
            if all(parts):
                return "|".join(parts)
        return self.ctx.natural_key_hint
