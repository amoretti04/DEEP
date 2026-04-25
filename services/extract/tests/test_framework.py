"""Tests for the declarative parser framework.

Covers the primitives (extract_field on HTML/XML/JSON, type conversion,
regex post-processing, transforms, PII tagging, required-field handling)
and the composite :class:`DeclarativeParser` behavior (root narrowing,
natural-key derivation, error/quarantine semantics).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from selectolax.parser import HTMLParser

from libs.provenance import build_envelope, new_ulid
from services.extract.framework import (
    DeclarativeParser,
    ExtractionConfig,
    FieldConfig,
    FieldType,
    ListConfig,
    ParseContext,
    ParseError,
    RecordPath,
    extract_field,
)
from services.extract.framework.config import PaginationConfig, PIITag


# ── Primitives: extract_field on HTML ────────────────────────────────
class TestExtractFieldHTML:
    HTML = """
    <div class="case">
      <h1 class="debtor">ACME S.p.A.</h1>
      <span class="case-no">R.G. 1234/2026</span>
      <time class="opened" datetime="2026-04-15">15 aprile 2026</time>
      <dd class="administrator">Avv. Mario Rossi</dd>
      <span class="amount">EUR 1.234.567,89</span>
    </div>
    """

    def _tree(self) -> object:
        return HTMLParser(self.HTML)

    def test_simple_text(self) -> None:
        f = extract_field(
            name="debtor_name",
            cfg=FieldConfig(selector="h1.debtor::text", required=True),
            tree=self._tree(),
        )
        assert f.value == "ACME S.p.A."
        assert f.provenance is not None
        assert f.provenance.field_name == "debtor_name"
        assert f.error is None

    def test_attribute(self) -> None:
        f = extract_field(
            name="opened_at",
            cfg=FieldConfig(
                type=FieldType.DATE,
                selector="time.opened::attr(datetime)",
                required=True,
            ),
            tree=self._tree(),
        )
        assert f.value == date(2026, 4, 15)
        assert f.error is None

    def test_regex_post_process(self) -> None:
        f = extract_field(
            name="case_number",
            cfg=FieldConfig(
                selector="span.case-no::text",
                regex=r"R\.G\.\s*(\d+/\d+)",
                required=True,
            ),
            tree=self._tree(),
        )
        assert f.value == "1234/2026"

    def test_decimal_with_locale(self) -> None:
        f = extract_field(
            name="amount",
            cfg=FieldConfig(
                type=FieldType.DECIMAL,
                selector="span.amount::text",
                regex=r"([\d.,]+)",
                decimal_thousands=".",
                decimal_point=",",
            ),
            tree=self._tree(),
        )
        assert f.value == Decimal("1234567.89")

    def test_missing_optional(self) -> None:
        f = extract_field(
            name="absent",
            cfg=FieldConfig(selector="span.nope::text", required=False),
            tree=self._tree(),
        )
        assert f.value is None
        assert f.error is None

    def test_missing_required(self) -> None:
        f = extract_field(
            name="absent",
            cfg=FieldConfig(selector="span.nope::text", required=True),
            tree=self._tree(),
        )
        assert f.value is None
        assert "required" in (f.error or "")

    def test_transforms(self) -> None:
        f = extract_field(
            name="administrator",
            cfg=FieldConfig(
                selector="dd.administrator::text",
                transforms=["trim_punctuation", "upper"],
            ),
            tree=self._tree(),
        )
        assert f.value == "AVV. MARIO ROSSI"
        assert f.provenance is not None
        assert f.provenance.transforms == ["trim_punctuation", "upper"]

    def test_pii_tag_propagates_via_config(self) -> None:
        cfg = FieldConfig(selector="h1.debtor::text", pii=PIITag.PERSONAL)
        assert cfg.pii is PIITag.PERSONAL


class TestExtractFieldJSON:
    PAYLOAD = {
        "case": {"number": "R-01", "opened": "2026-04-15"},
        "parties": [{"role": "debtor", "name": "ACME S.p.A."}],
    }

    def test_dotted_path(self) -> None:
        f = extract_field(
            name="case_number",
            cfg=FieldConfig(json_path="case.number"),
            tree=self.PAYLOAD,
        )
        assert f.value == "R-01"

    def test_indexed(self) -> None:
        f = extract_field(
            name="debtor_name",
            cfg=FieldConfig(json_path="parties[0].name"),
            tree=self.PAYLOAD,
        )
        assert f.value == "ACME S.p.A."

    def test_missing(self) -> None:
        f = extract_field(
            name="missing",
            cfg=FieldConfig(json_path="case.absent.value"),
            tree=self.PAYLOAD,
        )
        assert f.value is None
        assert f.error is None


class TestExtractFieldXML:
    XML = """<?xml version="1.0"?>
    <bodacc>
      <annonce>
        <immatriculation>
          <denomination>ACME SAS</denomination>
          <numeroIdentification>123456789</numeroIdentification>
        </immatriculation>
        <dateJugement>2026-04-15</dateJugement>
      </annonce>
    </bodacc>"""

    def test_xpath(self) -> None:
        f = extract_field(
            name="debtor_name",
            cfg=FieldConfig(xpath="//annonce/immatriculation/denomination/text()"),
            tree=self.XML,
        )
        assert f.value == "ACME SAS"


# ── DeclarativeParser composite behavior ─────────────────────────────
def _ctx() -> ParseContext:
    env = build_envelope(
        source_id="test",
        source_url="https://example.com/x",
        stable_natural_key="nk-1",
        fetched_at_utc=datetime(2026, 4, 21, tzinfo=UTC),
        published_at_local=None,
        raw_object_key="test/2026/04/21/" + "a" * 64 + ".html",
        raw_sha256="a" * 64,
        parser_version="test_v1.0.0",
        extractor_run_id=new_ulid(),
        data_owner="t",
        legal_basis="t",
    )
    return ParseContext(
        source_id="test",
        parser_version="test_v1.0.0",
        run_id=new_ulid(),
        envelope=env,
        raw_object_key=env.raw_object_key,
        source_url=env.source_url,
        natural_key_hint="fallback-key",
    )


class _DemoParser(DeclarativeParser):
    PARSER_ID = "parsers.demo_v1"
    VERSION = "1.0.0"
    config = ExtractionConfig(
        content_type="html",
        record=RecordPath(
            root_selector="div.case",
            fields={
                "debtor_name": FieldConfig(
                    selector="h1.debtor::text", required=True, pii=PIITag.PERSONAL,
                ),
                "case_number": FieldConfig(selector="span.case-no::text", required=True),
                "opened_at": FieldConfig(
                    type=FieldType.DATE,
                    selector="time.opened::attr(datetime)",
                    required=True,
                ),
                "administrator": FieldConfig(
                    selector="dd.administrator::text",
                    transforms=["trim_punctuation"],
                ),
            },
            natural_key_fields=["case_number"],
        ),
    )


class TestDeclarativeParser:
    GOOD = b"""
    <html><body>
      <div class="case">
        <h1 class="debtor">ACME S.p.A.</h1>
        <span class="case-no">1234/2026</span>
        <time class="opened" datetime="2026-04-15"></time>
        <dd class="administrator">Avv. Mario Rossi.</dd>
      </div>
    </body></html>
    """

    def test_parse_ok(self) -> None:
        parser = _DemoParser(_ctx())
        records = parser.parse(self.GOOD)
        assert len(records) == 1
        r = records[0]
        assert r.fields["debtor_name"] == "ACME S.p.A."
        assert r.fields["case_number"] == "1234/2026"
        assert r.fields["opened_at"] == date(2026, 4, 15)
        assert r.fields["administrator"] == "Avv. Mario Rossi"  # trailing period stripped
        assert r.natural_key == "1234/2026"
        assert set(r.field_provenance) == {
            "debtor_name", "case_number", "opened_at", "administrator",
        }
        assert r.confidence == 1.0

    def test_missing_required_raises_parseerror(self) -> None:
        bad = b"<html><body><div class='case'><h1 class='debtor'>x</h1></div></body></html>"
        parser = _DemoParser(_ctx())
        with pytest.raises(ParseError) as e:
            parser.parse(bad)
        assert "required" in str(e.value).lower()

    def test_root_selector_mismatch_raises(self) -> None:
        bad = b"<html><body><div class='not-case'>nothing</div></body></html>"
        parser = _DemoParser(_ctx())
        with pytest.raises(ParseError, match="root_selector"):
            parser.parse(bad)

    def test_natural_key_fallback(self) -> None:
        # Subclass that doesn't declare natural_key_fields — should fall
        # back to the context hint.
        class _NoKey(DeclarativeParser):
            PARSER_ID = "x"
            VERSION = "1.0.0"
            config = ExtractionConfig(
                content_type="html",
                record=RecordPath(
                    root_selector="div.case",
                    fields={
                        "debtor_name": FieldConfig(selector="h1.debtor::text", required=True),
                        "case_number": FieldConfig(selector="span.case-no::text", required=True),
                        "opened_at": FieldConfig(
                            type=FieldType.DATE,
                            selector="time.opened::attr(datetime)",
                            required=True,
                        ),
                    },
                ),
            )

        records = _NoKey(_ctx()).parse(self.GOOD)
        assert records[0].natural_key == "fallback-key"


# ── Config validation ─────────────────────────────────────────────────
class TestConfigValidation:
    def test_field_requires_a_selector(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FieldConfig()

    def test_list_requires_detail_locator(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ListConfig()

    def test_extraction_config_minimal(self) -> None:
        cfg = ExtractionConfig(
            record=RecordPath(
                fields={"x": FieldConfig(selector="p::text")},
            ),
        )
        assert cfg.content_type == "html"

    def test_pagination_defaults_to_none(self) -> None:
        p = PaginationConfig()
        assert p.type == "none"
        assert p.max_pages == 1
