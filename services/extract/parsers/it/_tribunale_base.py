"""Shared base for Italian tribunali insolvency-section parsers.

Italian tribunali publish procedural detail pages that are structurally
similar within the "Sezione Fallimentare" / "Procedure Concorsuali"
departments. Fields and selectors are the same; only the court name
differs. Concrete parsers subclass this and set ``COURT_NAME``.

The Milano reference parser (R2) shares this base for consistency. Any
selector change propagates to all Italian tribunale parsers through
the base config — which is exactly what we want for a shared CMS.

When a specific tribunale has a divergent DOM (some Italian courts
customize their portals), override :attr:`config` with a copy that has
the court-specific selectors. The postprocess contract is preserved.
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


class ItalianTribunaleParser(DeclarativeParser):
    """Base class for Italian tribunali insolvency-section parsers.

    Subclass this, set :attr:`COURT_NAME` and :attr:`PARSER_ID` /
    :attr:`VERSION`. The base ``config`` handles the rest.
    """

    #: Set on each subclass — used in ``postprocess`` and test assertions.
    COURT_NAME: ClassVar[str] = ""

    config = ExtractionConfig(
        content_type="html",
        list=ListConfig(
            detail_url_selector="table.filings tr td.case a::attr(href)",
            natural_key_selector="table.filings tr td.case a::text",
            published_at_selector="table.filings tr td.date::text",
            published_at_date_format="%d/%m/%Y",
            pagination=PaginationConfig(type="numbered", max_pages=50, param_name="page"),
        ),
        record=RecordPath(
            root_selector="div.case-detail",
            fields={
                "debtor_name": FieldConfig(
                    selector="h1.debtor::text",
                    required=True,
                    pii=PIITag.NON_PERSONAL,
                ),
                "case_number": FieldConfig(
                    selector="span.case-no::text",
                    regex=r"R\.G\.\s*(\d+/\d+)",
                    required=True,
                ),
                "proceeding_type_original": FieldConfig(
                    selector="dl.meta dd.type::text",
                    required=True,
                    transforms=["trim_punctuation"],
                ),
                "opened_at": FieldConfig(
                    type=FieldType.DATE,
                    selector="time.opened::attr(datetime)",
                    required=True,
                ),
                "administrator_name": FieldConfig(
                    selector="dl.meta dd.administrator::text",
                    pii=PIITag.PERSONAL,
                    transforms=["trim_punctuation"],
                ),
                "administrator_role": FieldConfig(
                    selector="dl.meta dd.administrator-role::text",
                    transforms=["trim_punctuation"],
                ),
                "codice_fiscale": FieldConfig(
                    selector="dl.meta dd.codice-fiscale::text",
                    regex=r"([A-Z0-9]{11,16})",
                ),
                "piva": FieldConfig(
                    selector="dl.meta dd.piva::text",
                    regex=r"(\d{11})",
                ),
                "judge_name": FieldConfig(
                    selector="dl.meta dd.judge::text",
                    pii=PIITag.PERSONAL,
                    transforms=["trim_punctuation"],
                ),
                "first_creditor_meeting_at": FieldConfig(
                    type=FieldType.DATETIME,
                    selector="time.creditor-meeting::attr(datetime)",
                ),
            },
            natural_key_fields=["case_number"],
        ),
    )

    def postprocess(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Map procedural label → unified taxonomy; fill court metadata."""
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
            fields["jurisdiction"] = "IT"

        return fields
