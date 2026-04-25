"""Parser for insolvenzbekanntmachungen.de — the joint insolvency portal
for all German Länder courts (CLAUDE.md / workbook sheet).

Key differences vs. the Italian tribunal parser:
* German procedural labels — mapped via libs.taxonomy.map_proceeding_type
  (covers Regelinsolvenzverfahren, Eigenverwaltung, Schutzschirmverfahren,
  StaRUG, vorläufiges Insolvenzverfahren).
* Court field is per-notice (Aachen, Aalen, ...) not fixed.
* Aktenzeichen (case number) format: "IN 123/26" or "IN 1234/26".
* Handelsregister number (HRB/HRA) captured for entity resolution.
* § 9 InsO notices carry a two-week minimum publication window; we treat
  the first-seen timestamp as the published_at (list page provides it).
"""

from __future__ import annotations

import re
from typing import Any

from libs.taxonomy import map_proceeding_type
from services.extract.framework import (
    DeclarativeParser,
    ExtractionConfig,
    FieldConfig,
    FieldType,
    ListConfig,
    RecordPath,
)
from services.extract.framework.config import PIITag, PaginationConfig


class InsolvenzbekanntmachungenParser(DeclarativeParser):
    """insolvenzbekanntmachungen.de detail-page parser."""

    PARSER_ID = "parsers.de.insolvenzbekanntmachungen_v1"
    VERSION = "1.0.0"

    config = ExtractionConfig(
        content_type="html",
        list=ListConfig(
            detail_url_selector="table.ergebnis tr td.az a::attr(href)",
            natural_key_selector="table.ergebnis tr td.az a::text",
            published_at_selector="table.ergebnis tr td.datum::text",
            published_at_date_format="%d.%m.%Y",
            pagination=PaginationConfig(type="numbered", max_pages=100, param_name="seite"),
        ),
        record=RecordPath(
            root_selector="div.bekanntmachung",
            fields={
                "court_name": FieldConfig(
                    selector="span.gericht::text",
                    required=True,
                ),
                "case_number": FieldConfig(
                    selector="span.aktenzeichen::text",
                    regex=r"((?:IN|HRB|HRA)\s*\d+/\d+)",
                    required=True,
                ),
                "debtor_name": FieldConfig(
                    selector="p.schuldner span.firma::text",
                    required=True,
                    pii=PIITag.NON_PERSONAL,  # legal entity name
                ),
                "debtor_address": FieldConfig(
                    selector="p.schuldner span.anschrift::text",
                ),
                "hrb_number": FieldConfig(
                    selector="p.register::text",
                    regex=r"(HRB\s*\d+)",
                ),
                "proceeding_type_original": FieldConfig(
                    selector="span.verfahrensart::text",
                    required=True,
                ),
                "opened_at": FieldConfig(
                    type=FieldType.DATE,
                    selector="time.eroeffnung::attr(datetime)",
                    required=True,
                ),
                "administrator_name": FieldConfig(
                    selector="p.verwalter span.name::text",
                    pii=PIITag.PERSONAL,
                ),
                "administrator_address": FieldConfig(
                    selector="p.verwalter span.anschrift::text",
                ),
                "notice_text": FieldConfig(
                    selector="div.bekanntmachungstext::text",
                ),
                "first_creditor_meeting_at": FieldConfig(
                    type=FieldType.DATETIME,
                    selector="time.glaeubigerversammlung::attr(datetime)",
                ),
            },
            natural_key_fields=["court_name", "case_number"],
        ),
    )

    def postprocess(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Map German procedural label to unified, set jurisdiction,
        pull the HRB number out for entity-resolution downstream."""
        original = fields.get("proceeding_type_original")
        if isinstance(original, str) and original:
            fields["proceeding_type"] = map_proceeding_type(original).value

        fields["jurisdiction"] = "DE"
        fields["court_case_number"] = fields.get("case_number")

        # HRB: "HRB 123456" → store just the numeric part too for joining
        # against Handelsregister / Unternehmensregister in R3 entity resolution.
        if (raw := fields.get("hrb_number")) and isinstance(raw, str):
            m = re.search(r"HRB\s*(\d+)", raw)
            if m:
                fields["hrb_number_numeric"] = m.group(1)

        return fields
