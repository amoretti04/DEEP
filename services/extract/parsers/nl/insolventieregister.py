"""Parser for Centraal Insolventieregister (CIR) — insolventies.rechtspraak.nl.

The Dutch central insolvency register exposes detail pages per case with
a consistent structure. Key Dutch procedural labels:

* faillissement        → LIQUIDATION
* surseance van betaling → MORATORIUM
* WHOA / schuldsanering → REORGANIZATION (WHOA is the Dutch Scheme).

Fields extracted match the canonical proceeding entity plus the RSIN
(Rechtspersonen en Samenwerkingsverbanden Informatienummer) or KvK
number for later entity resolution against the Kamer van Koophandel
business registry.
"""

from __future__ import annotations

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


class InsolventieregisterParser(DeclarativeParser):
    """Centraal Insolventieregister detail-page parser."""

    PARSER_ID = "parsers.nl.insolventieregister_v1"
    VERSION = "1.0.0"

    config = ExtractionConfig(
        content_type="html",
        list=ListConfig(
            detail_url_selector="table.resultaten tr td.zaak a::attr(href)",
            natural_key_selector="table.resultaten tr td.zaak a::text",
            published_at_selector="table.resultaten tr td.datum::text",
            published_at_date_format="%d-%m-%Y",
            pagination=PaginationConfig(type="numbered", max_pages=100, param_name="pagina"),
        ),
        record=RecordPath(
            root_selector="div.insolventie-detail",
            fields={
                "court_name": FieldConfig(
                    selector="span.rechtbank::text",
                    required=True,
                ),
                "case_number": FieldConfig(
                    selector="span.insolventienummer::text",
                    regex=r"(\S+/\d+)",
                    required=True,
                ),
                "debtor_name": FieldConfig(
                    selector="h1.schuldenaar::text",
                    required=True,
                    pii=PIITag.NON_PERSONAL,
                ),
                "debtor_address": FieldConfig(
                    selector="p.adres::text",
                ),
                "kvk_number": FieldConfig(
                    selector="dd.kvk::text",
                    regex=r"(\d{8})",
                ),
                "rsin": FieldConfig(
                    selector="dd.rsin::text",
                    regex=r"(\d{9})",
                ),
                "proceeding_type_original": FieldConfig(
                    selector="dd.soort::text",
                    required=True,
                ),
                "opened_at": FieldConfig(
                    type=FieldType.DATE,
                    selector="time.uitspraak::attr(datetime)",
                    required=True,
                ),
                "administrator_name": FieldConfig(
                    selector="dd.curator::text",
                    pii=PIITag.PERSONAL,
                ),
                "judge_name": FieldConfig(
                    selector="dd.rechter-commissaris::text",
                    pii=PIITag.PERSONAL,
                ),
                "closed_at": FieldConfig(
                    type=FieldType.DATE,
                    selector="time.einddatum::attr(datetime)",
                ),
            },
            natural_key_fields=["court_name", "case_number"],
        ),
    )

    def postprocess(self, fields: dict[str, Any]) -> dict[str, Any]:
        original = fields.get("proceeding_type_original")
        if isinstance(original, str) and original:
            fields["proceeding_type"] = map_proceeding_type(original).value

        fields["jurisdiction"] = "NL"
        fields["court_case_number"] = fields.get("case_number")
        return fields
