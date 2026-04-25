"""Centraal Insolventieregister canary regression test."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from libs.provenance import build_envelope, new_ulid
from services.extract.framework import ParseContext
from services.extract.parsers.nl.insolventieregister import InsolventieregisterParser

FIXTURE_DIR = Path(__file__).parent


def _ctx() -> ParseContext:
    env = build_envelope(
        source_id="nl-rechtspraak-cir",
        source_url="https://insolventies.rechtspraak.nl/details/F.14-26-123",
        stable_natural_key="F.14/26/123",
        fetched_at_utc=datetime(2026, 4, 15, tzinfo=UTC),
        published_at_local=None,
        raw_object_key="nl-rechtspraak-cir/2026/04/15/" + "a" * 64 + ".html",
        raw_sha256="a" * 64,
        parser_version="nl.insolventieregister_v1.0.0",
        extractor_run_id=new_ulid(),
        data_owner="team-ingest-nl",
        legal_basis="Art. 6(1)(f) GDPR — public insolvency register",
    )
    return ParseContext(
        source_id=env.source_id,
        parser_version=env.parser_version,
        run_id=env.extractor_run_id,
        envelope=env,
        raw_object_key=env.raw_object_key,
        source_url=env.source_url,
        natural_key_hint="F.14/26/123",
    )


class TestInsolventieregisterCanary:
    def test_parses_detail_page(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.html").read_bytes()
        records = InsolventieregisterParser(_ctx()).parse(raw)
        assert len(records) == 1
        r = records[0]

        assert r.fields["court_name"] == "Rechtbank Amsterdam"
        assert r.fields["case_number"] == "F.14/26/123"
        assert r.fields["court_case_number"] == "F.14/26/123"
        assert r.fields["debtor_name"] == "Voorbeeld Handel B.V."
        assert r.fields["debtor_address"] == "Herengracht 45, 1015 BC Amsterdam"
        assert r.fields["kvk_number"] == "12345678"
        assert r.fields["rsin"] == "123456789"
        assert r.fields["proceeding_type_original"] == "Faillissement"
        assert r.fields["proceeding_type"] == "LIQUIDATION"
        assert r.fields["opened_at"] == date(2026, 4, 14)
        assert r.fields["administrator_name"] == "Mr. drs. Jan de Vries"
        assert r.fields["judge_name"] == "Mr. A.B. van der Berg"
        assert r.fields["jurisdiction"] == "NL"

    def test_natural_key_combines_court_and_number(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.html").read_bytes()
        r = InsolventieregisterParser(_ctx()).parse(raw)[0]
        assert r.natural_key == "Rechtbank Amsterdam|F.14/26/123"

    def test_provenance_on_all_extracted_fields(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.html").read_bytes()
        r = InsolventieregisterParser(_ctx()).parse(raw)[0]
        # All the fields that should carry provenance
        for name in (
            "court_name", "case_number", "debtor_name",
            "kvk_number", "rsin", "proceeding_type_original",
            "opened_at", "administrator_name", "judge_name",
        ):
            assert name in r.field_provenance

    def test_missing_required_quarantines(self) -> None:
        from services.extract.framework import ParseError
        raw = (FIXTURE_DIR / "001_raw.html").read_bytes().replace(
            b'<h1 class="schuldenaar">Voorbeeld Handel B.V.</h1>', b"",
        )
        with pytest.raises(ParseError, match="required"):
            InsolventieregisterParser(_ctx()).parse(raw)
