"""Declarative extraction config — what a parser's YAML block looks like.

A Source Card YAML extends its ``parser:`` reference with an ``extraction:``
block that conforms to :class:`ExtractionConfig`. Example:

.. code-block:: yaml

   extraction:
     list:
       detail_url_selector: "table.filings tr td.case a::attr(href)"
       natural_key_selector: "table.filings tr td.case a::text"
       pagination:
         type: numbered
         max_pages: 50
     record:
       root: "div.case-detail"
       fields:
         debtor_name:
           type: string
           selector: "h1.debtor::text"
           required: true
           pii: personal   # scope-gate hint for R3 minimization
         case_number:
           type: string
           selector: "span.case-no::text"
           required: true
         opened_at:
           type: date
           selector: "time.opened::attr(datetime)"
           date_format: "%Y-%m-%d"
         proceeding_type_original:
           type: string
           selector: "dl.meta dd.type::text"
         administrator_name:
           type: string
           selector: "dl.meta dd.administrator::text"

The framework itself knows nothing about insolvency; it knows how to
apply selectors and type-convert. All domain specifics live in the YAML
(stable, reviewable, version-controlled) or in a small subclass override.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FieldType(str, Enum):
    """Canonical value types the extractor knows how to type-convert."""

    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"      # for monetary amounts (parses locale commas)
    DATE = "date"            # ISO or configurable strftime format
    DATETIME = "datetime"    # tz-aware where possible
    URL = "url"
    BOOLEAN = "boolean"
    LIST = "list"            # repeating field → list of strings


class PIITag(str, Enum):
    """Data-minimization tag attached to a field (CLAUDE.md §3.2).

    The normalizer uses this to decide whether to store a field, hash it,
    or drop it entirely. The importer/parser's job is only to declare
    intent — the enforcement is downstream.
    """

    NON_PERSONAL = "non_personal"
    PERSONAL = "personal"
    PERSONAL_SENSITIVE = "personal_sensitive"  # never stored


class FieldConfig(BaseModel):
    """One extracted field in the declarative config."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: FieldType = FieldType.STRING

    # Selector chain. Any of the following may be set; they are tried in
    # order until one matches. CSS-style ``::attr(href)`` and ``::text``
    # pseudo-elements are supported.
    selector: str | None = None
    xpath: str | None = None
    # JSON path for API sources (simple dot/bracket; nothing fancy).
    json_path: str | None = None
    # Regex applied to the matched text after selector. First capture group wins.
    regex: str | None = None

    # Type-conversion hints.
    date_format: str | None = None
    decimal_thousands: str = ","
    decimal_point: str = "."
    truthy: list[str] = Field(default_factory=lambda: ["true", "yes", "1", "si", "sí", "ja"])

    # Validation.
    required: bool = False
    strip: bool = True
    default: Any | None = None

    # Privacy classification (used by downstream minimization).
    pii: PIITag = PIITag.NON_PERSONAL

    # Optional transforms, applied in order after type conversion.
    # Each transform is a short DSL token: "upper", "lower", "nullempty",
    # "trim_punctuation". Keep the set small; new transforms require a
    # code change, not just a YAML change.
    transforms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_selector(self) -> FieldConfig:
        if not any([self.selector, self.xpath, self.json_path]):
            raise ValueError(
                "FieldConfig requires one of selector / xpath / json_path"
            )
        return self


class PaginationConfig(BaseModel):
    """How the list page paginates, if at all."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(default="none", description="none | numbered | cursor | rss")
    max_pages: int = Field(default=1, ge=1, le=10_000)
    next_selector: str | None = None  # for cursor: which anchor holds the next page URL
    param_name: str | None = None     # for numbered: query param to bump (default 'page')


class ListConfig(BaseModel):
    """List-page configuration — how to enumerate detail links."""

    model_config = ConfigDict(extra="forbid")

    # How to find each detail entry on the list page. Exactly one of these.
    detail_url_selector: str | None = None
    detail_url_xpath: str | None = None
    detail_url_json_path: str | None = None

    # How to pull the stable natural key for each entry. If omitted, we
    # derive it from the detail URL's last path segment + a sha1 of the
    # URL — a fallback that keeps record_uid idempotent.
    natural_key_selector: str | None = None
    natural_key_xpath: str | None = None
    natural_key_json_path: str | None = None

    # Optional: published_at_local from the list page (some sources show
    # the publication date in the list, not on the detail page).
    published_at_selector: str | None = None
    published_at_date_format: str | None = None

    pagination: PaginationConfig = PaginationConfig()

    @model_validator(mode="after")
    def _one_detail_locator(self) -> ListConfig:
        if not any(
            [self.detail_url_selector, self.detail_url_xpath, self.detail_url_json_path]
        ):
            raise ValueError(
                "ListConfig requires one of detail_url_selector / _xpath / _json_path"
            )
        return self


class RecordPath(BaseModel):
    """Detail-page configuration — root element + field map."""

    model_config = ConfigDict(extra="forbid")

    # Root selector/xpath. If omitted, the whole document is the root.
    root_selector: str | None = None
    root_xpath: str | None = None

    # Per-field extraction map.
    fields: dict[str, FieldConfig]

    # Optional list of fields that together form the natural key when
    # the list-level natural key wasn't captured. E.g.:
    #   natural_key_fields: ["court_name", "case_number"]
    natural_key_fields: list[str] = Field(default_factory=list)


class ExtractionConfig(BaseModel):
    """Top-level extraction config — ``extraction:`` block in the Source Card."""

    model_config = ConfigDict(extra="forbid")

    # Content type expected; helps dispatch parsers. ``html | xml | json``.
    content_type: str = "html"

    # List page config. Optional — some sources are API bulk dumps where
    # every detail record is already in the response.
    list: ListConfig | None = None

    # Detail / record config. Always present.
    record: RecordPath


class FieldProvenance(BaseModel):
    """Per-field provenance — where exactly did this value come from.

    Attached to every extracted field. Lets the UI answer "show me the
    original HTML/XML for *just* this field" with zero ambiguity, and
    gives the analyst-correction tool a precise anchor.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_name: str
    selector: str
    # Byte offsets into the raw artifact where the matched text lives.
    # Parsers that can't provide exact offsets (e.g. JSON path) leave
    # these as None — the selector alone is still enough to re-extract.
    start_offset: int | None = None
    end_offset: int | None = None
    # Length of raw text matched (pre-transform). Useful for UI highlight.
    raw_length: int | None = None
    # Transforms applied, as an ordered list — lets the analyst see that
    # "15/04/2026" was reshaped to "2026-04-15" via date_format.
    transforms: list[str] = Field(default_factory=list)
    # Confidence [0, 1]. 1.0 for direct structured matches, lower for OCR
    # / fuzzy fallbacks. Parsers decide; the normalizer may aggregate.
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
