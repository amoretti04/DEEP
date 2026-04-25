"""Shared base for French tribunaux de commerce (Greffe CMS) parsers.

French commercial courts (tribunaux de commerce) publish procedural
notices through a common Greffe CMS. Structure across Paris, Lyon,
Nanterre, etc. is similar enough that one base class parameterized on
``COURT_NAME`` covers all of them. This mirrors the Italian tribunale
pattern in ``it/_tribunale_base.py``.

Notes vs the Italian base:
* French case numbers include the tribunal and year: ``2026B01234``.
* ``mandataire`` vs ``curateur`` role distinction is preserved verbatim
  — the unified taxonomy mapping happens at postprocess time.
* SIREN (9 digits) captured for R4 entity resolution against Infogreffe.

Distinct from BODACC: BODACC is the bulk *post-publication* feed (one
XML daily); these Greffe pages are the originating detail pages at the
tribunal portal level, and they surface notices *faster* than BODACC.
"""

from __future__ import annotations

from typing import Any, ClassVar

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


class GreffeTribunalParser(DeclarativeParser):
    """Base class for Greffe CMS tribunaux de commerce parsers."""

    #: Set on each subclass.
    COURT_NAME: ClassVar[str] = ""

    config = ExtractionConfig(
        content_type="html",
        list=ListConfig(
            detail_url_selector="table.annonces tr td.ref a::attr(href)",
            natural_key_selector="table.annonces tr td.ref a::text",
            published_at_selector="table.annonces tr td.date::text",
            published_at_date_format="%d/%m/%Y",
            pagination=PaginationConfig(type="numbered", max_pages=50, param_name="page"),
        ),
        record=RecordPath(
            root_selector="div.annonce-detail",
            fields={
                "debtor_name": FieldConfig(
                    selector="h1.denomination::text",
                    required=True,
                    pii=PIITag.NON_PERSONAL,
                ),
                "debtor_legal_form": FieldConfig(
                    selector="span.forme-juridique::text",
                    transforms=["trim_punctuation"],
                ),
                "debtor_siren": FieldConfig(
                    selector="span.siren::text",
                    regex=r"(\d{9})",
                ),
                "debtor_rcs": FieldConfig(
                    selector="span.rcs::text",
                ),
                "debtor_naf": FieldConfig(
                    selector="span.code-ape::text",
                    regex=r"(\d{4}[A-Z])",
                ),
                "case_number": FieldConfig(
                    selector="span.numero-dossier::text",
                    regex=r"(\d{4}[A-Z]\d+)",
                    required=True,
                ),
                "proceeding_type_original": FieldConfig(
                    selector="dd.type-procedure::text",
                    required=True,
                    transforms=["trim_punctuation"],
                ),
                "opened_at": FieldConfig(
                    type=FieldType.DATE,
                    selector="time.jugement::attr(datetime)",
                    required=True,
                ),
                "administrator_name": FieldConfig(
                    selector="dd.mandataire::text",
                    pii=PIITag.PERSONAL,
                    transforms=["trim_punctuation"],
                ),
                "administrator_role": FieldConfig(
                    selector="dd.qualite::text",
                    transforms=["trim_punctuation"],
                ),
                "first_creditor_meeting_at": FieldConfig(
                    type=FieldType.DATETIME,
                    selector="time.assemblee-creanciers::attr(datetime)",
                ),
            },
            natural_key_fields=["case_number"],
        ),
    )

    def postprocess(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Map the French procedural label to the unified taxonomy."""
        if not self.COURT_NAME:
            raise RuntimeError(
                f"{type(self).__name__} must set COURT_NAME class attribute"
            )

        original = fields.get("proceeding_type_original")
        if isinstance(original, str) and original:
            fields["proceeding_type"] = map_proceeding_type(original).value

        if (cn := fields.get("case_number")) and isinstance(cn, str):
            fields["court_case_number"] = cn
            fields["court_name"] = self.COURT_NAME
            fields["jurisdiction"] = "FR"

        return fields
