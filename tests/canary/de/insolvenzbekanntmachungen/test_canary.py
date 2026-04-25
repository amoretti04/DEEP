"""Canary regression test for Insolvenzbekanntmachungen parser."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from libs.provenance import build_envelope, new_ulid
from services.extract.framework import ParseContext
from services.extract.parsers.de.insolvenzbekanntmachungen import (
    InsolvenzbekanntmachungenParser,
)

FIXTURE_DIR = Path(__file__).parent


def _ctx(natural_key_hint: str = "hint") -> ParseContext:
    env = build_envelope(
        source_id="de-justiz-onlinedienste-insolvenzbekanntmachungen",
        source_url="https://neu.insolvenzbekanntmachungen.de/ap/details?id=001",
        stable_natural_key=natural_key_hint,
        fetched_at_utc=datetime(2026, 4, 21, tzinfo=UTC),
        published_at_local=None,
        raw_object_key="de-justiz-onlinedienste-insolvenzbekanntmachungen/2026/04/21/"
                        + "a" * 64 + ".html",
        raw_sha256="a" * 64,
        parser_version="de.insolvenzbekanntmachungen_v1.0.0",
        extractor_run_id=new_ulid(),
        data_owner="team-ingest-de",
        legal_basis="Art. 6(1)(f) GDPR — § 9 InsO public notices",
    )
    return ParseContext(
        source_id=env.source_id,
        parser_version=env.parser_version,
        run_id=env.extractor_run_id,
        envelope=env,
        raw_object_key=env.raw_object_key,
        source_url=env.source_url,
        natural_key_hint=natural_key_hint,
    )


class TestInsolvenzbekanntmachungenCanary:
    def test_canary_001_reproduces_expected(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.html").read_bytes()
        expected = json.loads((FIXTURE_DIR / "001_expected.json").read_text())

        parser = InsolvenzbekanntmachungenParser(_ctx())
        records = parser.parse(raw)
        assert len(records) == 1
        rec = records[0]

        assert rec.natural_key == expected["natural_key"]

        for field_name, exp in expected["fields"].items():
            actual = rec.fields.get(field_name)
            if isinstance(actual, date):
                actual = actual.isoformat()
            elif hasattr(actual, "isoformat"):
                actual = actual.isoformat()
            assert actual == exp, (
                f"field {field_name!r}: expected {exp!r}, got {actual!r}"
            )

        for field_name in expected["provenance_fields"]:
            assert field_name in rec.field_provenance
            assert rec.field_provenance[field_name].selector

        assert rec.confidence == pytest.approx(expected["confidence"])

    def test_regelinsolvenzverfahren_maps_to_liquidation(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.html").read_bytes()
        parser = InsolvenzbekanntmachungenParser(_ctx())
        rec = parser.parse(raw)[0]
        assert rec.fields["proceeding_type"] == "LIQUIDATION"
        assert rec.fields["proceeding_type_original"] == "Regelinsolvenzverfahren"

    def test_hrb_number_is_parsed_to_numeric(self) -> None:
        """HRB is stored both as 'HRB 987654' (display) and '987654' (join key)."""
        raw = (FIXTURE_DIR / "001_raw.html").read_bytes()
        parser = InsolvenzbekanntmachungenParser(_ctx())
        rec = parser.parse(raw)[0]
        assert rec.fields["hrb_number"] == "HRB 987654"
        assert rec.fields["hrb_number_numeric"] == "987654"

    def test_missing_required_quarantines(self) -> None:
        from services.extract.framework import ParseError

        raw = (FIXTURE_DIR / "001_raw.html").read_bytes().replace(
            b'<span class="firma">Musterwerke GmbH</span>', b"",
        )
        parser = InsolvenzbekanntmachungenParser(_ctx())
        with pytest.raises(ParseError, match="required"):
            parser.parse(raw)
