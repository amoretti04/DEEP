"""BODACC canary — one XML bulletin yields three parsed records.

This test is particularly important because BODACC is the first source
using the bulk-XML parser variant. If this stays green, the pattern
generalizes to BOE, Insolvenzbekanntmachungen's RSS bulk, and anything
else that's one-file-many-records.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from libs.provenance import build_envelope, new_ulid
from services.extract.framework import ParseContext
from services.extract.parsers.fr.bodacc import BodaccParser

FIXTURE_DIR = Path(__file__).parent


def _ctx() -> ParseContext:
    env = build_envelope(
        source_id="fr-bodacc-b",
        source_url="https://echanges.dila.gouv.fr/OPENDATA/BODACC/BODACC_B_20260415.xml",
        stable_natural_key="bodacc-b-20260415",
        fetched_at_utc=datetime(2026, 4, 15, 8, 0, tzinfo=UTC),
        published_at_local=None,
        raw_object_key="fr-bodacc-b/2026/04/15/" + "a" * 64 + ".xml",
        raw_sha256="a" * 64,
        parser_version="fr.bodacc_v1.0.0",
        extractor_run_id=new_ulid(),
        data_owner="team-ingest-fr",
        legal_basis="Art. 6(1)(f) GDPR — statutory publication (BODACC)",
    )
    return ParseContext(
        source_id=env.source_id,
        parser_version=env.parser_version,
        run_id=env.extractor_run_id,
        envelope=env,
        raw_object_key=env.raw_object_key,
        source_url=env.source_url,
        natural_key_hint="bodacc-b-20260415",
    )


class TestBodaccCanary:
    def test_yields_three_records(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        records = BodaccParser(_ctx()).parse(raw)
        assert len(records) == 3

    def test_record_field_extraction(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        records = BodaccParser(_ctx()).parse(raw)

        # Annonce 1001 — Liquidation judiciaire, Paris
        r1 = records[0]
        assert r1.fields["annonce_number"] == "1001"
        assert r1.fields["debtor_name"] == "Exemple Manufacture SARL"
        assert r1.fields["debtor_siren"] == "123456789"
        assert r1.fields["debtor_naf"] == "2511Z"
        assert r1.fields["tribunal_name"] == "Tribunal de commerce de Paris"
        assert r1.fields["proceeding_type_code"] == "LJ"
        assert r1.fields["proceeding_type"] == "LIQUIDATION"
        assert r1.fields["proceeding_type_original"] == "Liquidation judiciaire"
        assert r1.fields["administrator_name"] == "Maître Jean Dupont"
        assert r1.fields["administrator_role"] == "Liquidateur judiciaire"
        assert r1.fields["jurisdiction"] == "FR"

    def test_type_codes_all_map(self) -> None:
        """All three BODACC type codes in the fixture must resolve to unified codes."""
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        records = BodaccParser(_ctx()).parse(raw)
        mapping = {r.fields["proceeding_type_code"]: r.fields["proceeding_type"] for r in records}
        assert mapping == {
            "LJ": "LIQUIDATION",
            "RJ": "REORGANIZATION",
            "SV": "REORGANIZATION",
        }

    def test_natural_key_includes_publication_date(self) -> None:
        """Natural key must be (annonce_number, publication_date) — stable and unique."""
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        records = BodaccParser(_ctx()).parse(raw)
        keys = [r.natural_key for r in records]
        assert keys == [
            "1001|2026-04-15",
            "1002|2026-04-15",
            "1003|2026-04-15",
        ]
        assert len(set(keys)) == 3  # all distinct

    def test_provenance_on_every_field(self) -> None:
        """Every extracted field must carry field-level provenance."""
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        records = BodaccParser(_ctx()).parse(raw)
        r = records[0]
        for field_name in (
            "annonce_number", "publication_date", "tribunal_name",
            "debtor_name", "debtor_siren", "proceeding_type_code", "opened_at",
        ):
            assert field_name in r.field_provenance, f"missing provenance for {field_name}"
            p = r.field_provenance[field_name]
            assert p.selector.startswith("xpath=")

    def test_invalid_xml_raises_parseerror(self) -> None:
        from services.extract.framework import ParseError

        with pytest.raises(ParseError, match="invalid XML"):
            BodaccParser(_ctx()).parse(b"not xml at all <<<")

    def test_empty_bulletin_yields_empty_list(self) -> None:
        """A bulletin with no <annonce> elements is valid (some days are empty)."""
        empty = b"""<?xml version="1.0"?><BODACC_B><parution><dateParution>2026-04-13</dateParution></parution></BODACC_B>"""
        records = BodaccParser(_ctx()).parse(empty)
        assert records == []

    def test_partial_record_skipped_not_fatal(self) -> None:
        """A single broken annonce in a bulletin shouldn't kill the whole batch."""
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        # Replace annonce 1002's required numeroAnnonce with nothing.
        corrupted = raw.replace(b"<numeroAnnonce>1002</numeroAnnonce>", b"")
        records = BodaccParser(_ctx()).parse(corrupted)
        # We lose the broken record but keep the other two.
        assert len(records) == 2
        assert {r.fields["annonce_number"] for r in records} == {"1001", "1003"}
